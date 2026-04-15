/**
 * BackendManager – auto-discovers and manages the kendr gateway + UI servers.
 *
 * gateway_server.py starts BOTH:
 *   • Gateway  →  http://127.0.0.1:8790  (agent execution)
 *   • UI       →  http://127.0.0.1:2151  (HTTP API used by the Electron renderer)
 *
 * Packaged mode (app.isPackaged === true):
 *   Prefer the standalone backend bundle at process.resourcesPath/kendr-backend/.
 *   Fall back to packaged Python source at process.resourcesPath/kendr-backend-source/.
 *   When the source fallback is used, a venv is created on first run at ~/.kendr/venv.
 *
 * Development mode:
 *   Falls back to system Python + gateway_server.py found by walking up dirs.
 */
import { spawn, execFile } from 'child_process'
import http from 'http'
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'fs'
import { dirname, join } from 'path'
import { app } from 'electron'
import os from 'os'

const UI_PORT      = 2151
const GATEWAY_PORT = 8790
const KENDR_HOME_DIR = join(os.homedir(), '.kendr')

/** Semver stored in ~/.kendr/venv-version to detect when the backend was updated */
const BACKEND_VERSION = (() => {
  try {
    const pkgPath = new URL(import.meta.url).pathname
      .replace(/^\/([A-Z]:)/, '$1')
      .replace(/[\\/]out[\\/]main[\\/]backend\.js$/, '/package.json')
    return JSON.parse(readFileSync(pkgPath, 'utf-8')).version
  } catch {
    return '0.0.0'
  }
})()

export class BackendManager {
  constructor(store) {
    this.store = store
    this._proc      = null
    this._logs      = []            // rolling last-200 lines
    this._status    = {
      gateway:   'stopped',         // stopped | starting | running | error
      ui:        'stopped',
      pid:       null,
      kendrRoot: null,
      error:     null,
      setup:     null,              // null | { phase, pct, message }
    }
    this._listeners    = []         // (status) => void  — push to renderer
    this._healthTimer  = null
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  status() { return { ...this._status, logs: [...this._logs] } }
  onChange(fn) { this._listeners.push(fn) }

  async startIfNeeded() {
    const [uiOk, gwOk] = await Promise.all([
      this._ping(UI_PORT), this._ping(GATEWAY_PORT)
    ])
    if (uiOk && gwOk) {
      this._set({ gateway: 'running', ui: 'running' })
      this._startHealthWatch()
      return { ok: true, already: true }
    }
    if (uiOk || gwOk) {
      this._set({
        gateway: gwOk ? 'running' : 'starting',
        ui:      uiOk ? 'running' : 'starting',
      })
      this._startHealthWatch()
    }
    return this.start()
  }

  async start() {
    if (this._status.gateway === 'running' && this._status.ui === 'running') {
      return { ok: true, already: true }
    }

    let command
    let args
    let cwd
    let launchRoot
    let extraEnv = {}

    const bundledExecutable = this._findBundledBackendExecutable()
    if (bundledExecutable) {
      command = bundledExecutable
      args = []
      cwd = dirname(bundledExecutable)
      launchRoot = cwd
      this._log(`[backend] bundled executable: ${bundledExecutable}`)
    } else {
      const kendrRoot = this._findKendrRoot()
      if (!kendrRoot) {
        this._set({
          gateway: 'error', ui: 'error',
          error: 'Cannot locate the packaged backend. Reinstall Kendr or set kendrRoot in Settings.',
        })
        return { error: this._status.error }
      }

      let python
      try {
        python = await this._resolvePython(kendrRoot)
      } catch (err) {
        this._set({ gateway: 'error', ui: 'error', error: err.message })
        return { error: err.message }
      }

      const gatewayScript = join(kendrRoot, 'gateway_server.py')
      command = python
      args = [gatewayScript]
      cwd = kendrRoot
      launchRoot = kendrRoot
      extraEnv = { PYTHONPATH: kendrRoot }
      this._log(`[backend] python: ${python}`)
      this._log(`[backend] script: ${gatewayScript}`)
    }

    this._set({ gateway: 'starting', ui: 'starting', error: null, kendrRoot: launchRoot, setup: null })

    return new Promise((resolve) => {
      try {
        this._proc = spawn(command, args, {
          cwd,
          env: {
            ...process.env,
            ...this._runtimeEnv(),
            KENDR_UI_ENABLED:  '1',
            GATEWAY_PORT:      String(GATEWAY_PORT),
            KENDR_UI_PORT:     String(UI_PORT),
            PYTHONUNBUFFERED:  '1',
            ...extraEnv,
            ...this._providerEnv(),
          },
          stdio:       ['ignore', 'pipe', 'pipe'],
          windowsHide: true,
        })

        this._status.pid = this._proc.pid
        let resolved = false

        const tryResolve = () => {
          if (!resolved) { resolved = true; resolve({ ok: true }) }
        }

        const handleLine = (line) => {
          this._log(line)
          if (line.includes('Gateway server running')) {
            this._set({ gateway: 'running' }); tryResolve()
          }
          if (line.includes('Kendr UI running') || line.includes('UI server') || line.includes('2151')) {
            this._set({ ui: 'running' }); tryResolve()
          }
        }

        let stdoutBuf = '', stderrBuf = ''
        this._proc.stdout?.on('data', d => {
          stdoutBuf += d.toString()
          const lines = stdoutBuf.split('\n'); stdoutBuf = lines.pop()
          lines.forEach(handleLine)
        })
        this._proc.stderr?.on('data', d => {
          stderrBuf += d.toString()
          const lines = stderrBuf.split('\n'); stderrBuf = lines.pop()
          lines.forEach(l => this._log(`[stderr] ${l}`))
        })

        this._proc.on('error', err => {
          this._log(`[backend] spawn error: ${err.message}`)
          this._set({ gateway: 'error', ui: 'error', error: err.message, pid: null })
          if (!resolved) { resolved = true; resolve({ error: err.message }) }
        })

        this._proc.on('exit', (code, signal) => {
          this._log(`[backend] exited  code=${code} signal=${signal}`)
          this._proc = null; this._status.pid = null
          if (this._status.gateway !== 'stopped') {
            this._set({
              gateway: code === 0 ? 'stopped' : 'error',
              ui: 'stopped',
              error: code ? `Exited ${code}` : null,
            })
          }
          this._stopHealthWatch()
        })

        // Fallback: health-check after 12 s
        setTimeout(async () => {
          const [uiOk, gwOk] = await Promise.all([this._ping(UI_PORT), this._ping(GATEWAY_PORT)])
          if (uiOk)  this._set({ ui: 'running' })
          if (gwOk)  this._set({ gateway: 'running' })
          if (!resolved) {
            resolved = true
            if (uiOk || gwOk) resolve({ ok: true })
            else {
              this._set({ ui: 'error', gateway: 'error', error: 'Did not respond within 12 s' })
              resolve({ error: 'Did not respond within 12 s' })
            }
          }
        }, 12000)

        this._startHealthWatch()
      } catch (err) {
        this._set({ gateway: 'error', ui: 'error', error: err.message, pid: null })
        resolve({ error: err.message })
      }
    })
  }

  stop() {
    this._stopHealthWatch()
    if (this._proc) {
      try { this._proc.kill('SIGTERM') } catch (_) {}
      this._proc = null
    }
    this._set({ gateway: 'stopped', ui: 'stopped', pid: null })
    return { ok: true }
  }

  async restart() {
    this.stop()
    await new Promise(r => setTimeout(r, 600))
    return this.start()
  }

  getLogs() { return [...this._logs] }

  // ── Python / venv resolution ────────────────────────────────────────────────

  /**
   * Returns the python executable to use.
   * - Packaged app: creates/reuses a venv at ~/.kendr/venv
   * - Dev mode:     uses store.pythonPath or falls back to python/python3
   */
  async _resolvePython(kendrRoot) {
    if (!app.isPackaged) {
      return this.store.get('pythonPath') || 'python'
    }
    return this._ensureVenv(kendrRoot)
  }

  /**
   * Creates (or reuses) a venv at ~/.kendr/venv.
   * Installs the bundled kendr package the first time or after a version bump.
   * Pushes setup progress events so the renderer can show a setup screen.
   */
  async _ensureVenv(kendrRoot) {
    const kendrDir  = join(os.homedir(), '.kendr')
    const venvDir   = join(kendrDir, 'venv')
    const venvMark  = join(kendrDir, 'venv-version')
    const isWin     = process.platform === 'win32'
    const venvPy    = isWin
      ? join(venvDir, 'Scripts', 'python.exe')
      : join(venvDir, 'bin', 'python')
    const venvPip   = isWin
      ? join(venvDir, 'Scripts', 'pip.exe')
      : join(venvDir, 'bin', 'pip')

    mkdirSync(kendrDir, { recursive: true })

    // Check if venv is current
    const installedVersion = existsSync(venvMark)
      ? readFileSync(venvMark, 'utf-8').trim()
      : ''
    const needsSetup = !existsSync(venvPy) || installedVersion !== BACKEND_VERSION

    if (!needsSetup) {
      this._log(`[venv] Using existing venv (v${installedVersion})`)
      return venvPy
    }

    this._log(`[venv] Setting up venv at ${venvDir} (was: "${installedVersion}", need: "${BACKEND_VERSION}")`)
    this._set({ gateway: 'starting', ui: 'starting', setup: { phase: 'setup', pct: 0, message: 'Preparing Python environment…' } })

    // ── Find system Python ─────────────────────────────────────────────────
    const sysPython = await this._findSystemPython()
    if (!sysPython) {
      throw new Error(
        'Python 3.10+ is required but was not found.\n' +
        'Install from https://python.org/downloads and relaunch Kendr.'
      )
    }
    this._log(`[venv] System python: ${sysPython}`)

    // ── Create venv ────────────────────────────────────────────────────────
    this._set({ setup: { phase: 'venv', pct: 10, message: 'Creating virtual environment…' } })
    await this._run(sysPython, ['-m', 'venv', venvDir])
    this._log(`[venv] venv created`)

    // ── Upgrade pip ────────────────────────────────────────────────────────
    this._set({ setup: { phase: 'pip', pct: 20, message: 'Upgrading pip…' } })
    await this._run(venvPy, ['-m', 'pip', 'install', '--upgrade', 'pip', '--quiet'])

    // ── Install kendr from bundled source ──────────────────────────────────
    this._set({ setup: { phase: 'install', pct: 30, message: 'Installing Kendr backend (this takes a few minutes on first run)…' } })
    this._log(`[venv] Installing from ${kendrRoot}`)

    // Stream pip output so the renderer can show progress
    await this._runStreaming(venvPip, ['install', kendrRoot, '--quiet', '--progress-bar', 'off'],
      (line) => {
        this._log(`[pip] ${line}`)
        // Bump percentage as packages are downloaded
        const cur = this._status.setup?.pct ?? 30
        if (cur < 90) this._set({ setup: { ...this._status.setup, pct: cur + 1 } })
      }
    )

    // ── Mark complete ──────────────────────────────────────────────────────
    writeFileSync(venvMark, BACKEND_VERSION, 'utf-8')
    this._set({ setup: { phase: 'done', pct: 100, message: 'Setup complete.' } })
    this._log(`[venv] Setup complete — v${BACKEND_VERSION}`)

    return venvPy
  }

  /** Find the first system python that is ≥ 3.10 */
  async _findSystemPython() {
    const candidates = process.platform === 'win32'
      ? ['python', 'python3', 'py']
      : ['python3', 'python', 'python3.12', 'python3.11', 'python3.10']

    for (const cmd of candidates) {
      try {
        const ver = await this._runOutput(cmd, ['--version'])
        const m = ver.match(/Python (\d+)\.(\d+)/)
        if (m && (parseInt(m[1]) > 3 || (parseInt(m[1]) === 3 && parseInt(m[2]) >= 10))) {
          return cmd
        }
      } catch { /* not found */ }
    }
    return null
  }

  // ── Root discovery ──────────────────────────────────────────────────────────

  _findKendrRoot() {
    // 1. Explicitly saved setting
    const saved = this.store.get('kendrRoot')
    if (saved && existsSync(join(saved, 'gateway_server.py'))) return saved

    // 2. Packaged app — bundled source fallback in resources
    if (app.isPackaged) {
      const bundled = join(process.resourcesPath, 'kendr-backend-source')
      if (existsSync(join(bundled, 'gateway_server.py'))) {
        this.store.set('kendrRoot', bundled)
        return bundled
      }
    }

    // 3. Dev mode — walk up from known anchors
    const anchors = [
      app.getAppPath(),
      process.cwd(),
      new URL(import.meta.url).pathname
        .replace(/^\/([A-Z]:)/, '$1')
        .replace(/[\\/]out[\\/]main[\\/]backend\.js$/, ''),
    ]

    for (const anchor of anchors) {
      for (let up = 0; up <= 4; up++) {
        let candidate = anchor
        for (let i = 0; i < up; i++) candidate = join(candidate, '..')
        if (existsSync(join(candidate, 'gateway_server.py'))) {
          this.store.set('kendrRoot', candidate)
          return candidate
        }
      }
    }
    return null
  }

  _findBundledBackendExecutable() {
    if (!app.isPackaged) return null
    const bundleRoot = join(process.resourcesPath, 'kendr-backend')
    const executable = process.platform === 'win32'
      ? join(bundleRoot, 'kendr-backend.exe')
      : join(bundleRoot, 'kendr-backend')
    return existsSync(executable) ? executable : null
  }

  _runtimeEnv() {
    mkdirSync(KENDR_HOME_DIR, { recursive: true })
    return {
      KENDR_HOME: KENDR_HOME_DIR,
      KENDR_DB_PATH: join(KENDR_HOME_DIR, 'agent_workflow.sqlite3'),
    }
  }

  // ── Internals ───────────────────────────────────────────────────────────────

  _set(patch) {
    Object.assign(this._status, patch)
    const snap = this.status()
    this._listeners.forEach(fn => { try { fn(snap) } catch (_) {} })
  }

  _log(line) {
    if (!line?.trim()) return
    this._logs.push(line)
    if (this._logs.length > 200) this._logs.shift()
  }

  _ping(port) {
    return new Promise(resolve => {
      const req = http.get({ hostname: '127.0.0.1', port, path: '/health', timeout: 1500 }, res => {
        resolve(res.statusCode < 500)
      })
      req.on('error',   () => resolve(false))
      req.on('timeout', () => { req.destroy(); resolve(false) })
    })
  }

  _startHealthWatch() {
    this._stopHealthWatch()
    this._healthTimer = setInterval(async () => {
      const [uiOk, gwOk] = await Promise.all([this._ping(UI_PORT), this._ping(GATEWAY_PORT)])
      let changed = false
      if (uiOk  && this._status.ui      !== 'running') { this._status.ui      = 'running'; changed = true }
      if (!uiOk && this._status.ui      === 'running') { this._status.ui      = 'error';   changed = true }
      if (gwOk  && this._status.gateway !== 'running') { this._status.gateway = 'running'; changed = true }
      if (!gwOk && this._status.gateway === 'running') { this._status.gateway = 'error';   changed = true }
      if (changed) this._set({})
    }, 5000)
  }

  _stopHealthWatch() {
    if (this._healthTimer) { clearInterval(this._healthTimer); this._healthTimer = null }
  }

  _providerEnv() {
    return Object.fromEntries(
      [
        ['anthropicKey',  'ANTHROPIC_API_KEY'],
        ['openaiKey',     'OPENAI_API_KEY'],
        ['openaiOrgId',   'OPENAI_ORG_ID'],
        ['googleKey',     'GOOGLE_API_KEY'],
        ['xaiKey',        'XAI_API_KEY'],
        ['hfToken',       'HUGGINGFACEHUB_API_TOKEN'],
        ['tavilyKey',     'TAVILY_API_KEY'],
        ['braveKey',      'BRAVE_API_KEY'],
        ['serperKey',     'SERPER_API_KEY'],
      ]
        .map(([k, env]) => [env, String(this.store.get(k) || '').trim()])
        .filter(([, v]) => v)
    )
  }

  /** Run a command, resolve when it exits 0, reject otherwise. */
  _run(cmd, args) {
    return new Promise((resolve, reject) => {
      const child = spawn(cmd, args, { stdio: 'ignore', windowsHide: true })
      child.on('error', reject)
      child.on('exit', code => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)))
    })
  }

  /** Run a command and return its combined stdout+stderr as a string. */
  _runOutput(cmd, args) {
    return new Promise((resolve, reject) => {
      execFile(cmd, args, (err, stdout, stderr) => {
        if (err && !stdout && !stderr) return reject(err)
        resolve((stdout + stderr).trim())
      })
    })
  }

  /** Run a command and stream each output line to onLine(). */
  _runStreaming(cmd, args, onLine) {
    return new Promise((resolve, reject) => {
      const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true })
      let buf = ''
      const handle = chunk => {
        buf += chunk.toString()
        const lines = buf.split('\n'); buf = lines.pop()
        lines.forEach(l => { try { onLine(l) } catch (_) {} })
      }
      child.stdout?.on('data', handle)
      child.stderr?.on('data', handle)
      child.on('error', reject)
      child.on('exit', code => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)))
    })
  }
}
