import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron'
import { randomUUID } from 'crypto'
import { join } from 'path'
import { existsSync, readdirSync, statSync, readFileSync, writeFileSync, mkdirSync, rmSync, renameSync } from 'fs'
import { exec } from 'child_process'
import { Store } from './store.js'
import os from 'os'
import path from 'path'
import { BackendManager } from './backend.js'
import { UpdateManager } from './updater.js'

let pty
try {
  pty = require('node-pty')
} catch (_) {
  pty = null
}

const store = new Store({
  defaults: {
    backendUrl:      'http://127.0.0.1:2151',
    gatewayUrl:      'http://127.0.0.1:8790',
    pythonPath:      'python',
    kendrRoot:       '',    // auto-detected; override in Settings if needed
    projectRoot:     '',
    theme:           'dark',
    fontSize:        14,
    tabSize:         2,
    fontFamily:      "'Cascadia Code', 'Fira Code', monospace",
    gitName:         os.userInfo().username,
    gitEmail:        '',
    githubPat:       '',
    autoStartBackend: true,
    updatesEnabled:  true,
    updateBaseUrl:   '',
    updateChannel:   'latest',
    autoDownloadUpdates: true,
    autoInstallOnQuit: true,
    allowPrereleaseUpdates: false,
    updateCheckIntervalMinutes: 240,
    windowBounds:    { width: 1400, height: 900 },
    sidebarWidth:    260,
    chatPanelWidth:  380,
    terminalHeight:  220,
    modelDownloadDir: join(os.homedir(), '.kendr', 'models'),
    gpuLayers:       0,
    contextSize:     4096,
    threads:         4,
    chatHistoryRetentionDays: 14
  }
})

const backend = new BackendManager(store)
const updates = new UpdateManager(store, { getMainWindow: () => mainWindow })
const ptyProcesses = new Map()
let mainWindow = null
let rendererRecoveryAttempts = 0
let rendererRecoveryResetTimer = null

function resetRendererRecoveryBudgetSoon() {
  if (rendererRecoveryResetTimer) clearTimeout(rendererRecoveryResetTimer)
  rendererRecoveryResetTimer = setTimeout(() => {
    rendererRecoveryAttempts = 0
    rendererRecoveryResetTimer = null
  }, 30000)
}

function reloadMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

function createWindow() {
  const bounds = store.get('windowBounds')

  mainWindow = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    minWidth: 800,
    minHeight: 600,
    frame: false,
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#161b22',
      symbolColor: '#7d8590',
      height: 32
    },
    backgroundColor: '#0d0f14',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false // allow localhost API calls
    },
    icon: join(__dirname, '../../resources/icon.png')
  })

  mainWindow.on('resize', () => {
    store.set('windowBounds', mainWindow.getBounds())
  })

  mainWindow.on('close', () => {
    // Kill all PTY processes
    for (const [id, proc] of ptyProcesses) {
      try { proc.kill() } catch (_) {}
    }
    ptyProcesses.clear()
  })

  mainWindow.webContents.on('render-process-gone', (_, details) => {
    console.error('[renderer] process gone', details)
    if (rendererRecoveryAttempts >= 2) return
    rendererRecoveryAttempts += 1
    resetRendererRecoveryBudgetSoon()
    setTimeout(() => {
      reloadMainWindow()
    }, 300)
  })

  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(async () => {
  createWindow()

  // Push every backend status change to the renderer in real time
  backend.onChange((status) => {
    mainWindow?.webContents.send('backend:status-push', status)
  })
  updates.onChange((status) => {
    mainWindow?.webContents.send('updates:status-push', status)
  })
  updates.init()

  // Auto-start gateway + UI server
  if (store.get('autoStartBackend')) {
    // Small delay so renderer is ready to receive the first status push
    setTimeout(() => backend.startIfNeeded().catch(() => {}), 800)
  } else {
    // Still check if they are already running externally
    backend.startIfNeeded().catch(() => {})
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  backend.stop()
  if (process.platform !== 'darwin') app.quit()
})

// ─── Window Controls ─────────────────────────────────────────────────────────
ipcMain.handle('window:minimize', () => mainWindow?.minimize())
ipcMain.handle('window:maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize()
  else mainWindow?.maximize()
})
ipcMain.handle('window:close', () => mainWindow?.close())
ipcMain.handle('window:isMaximized', () => mainWindow?.isMaximized() ?? false)

// ─── Settings ────────────────────────────────────────────────────────────────
ipcMain.handle('settings:get', (_, key) => key ? store.get(key) : store.store)
ipcMain.handle('settings:set', (_, key, value) => {
  store.set(key, value)
  if (updates.isUpdateSettingKey(key)) {
    updates.refreshConfig()
  }
  return true
})
ipcMain.handle('settings:getAll', () => store.store)

// ─── Application Updates ─────────────────────────────────────────────────────
ipcMain.handle('updates:status', () => updates.status())
ipcMain.handle('updates:check', () => updates.checkForUpdates({ manual: true }))
ipcMain.handle('updates:download', () => updates.downloadUpdate())
ipcMain.handle('updates:install', () => ({ ok: updates.quitAndInstall() }))

// ─── Backend Management ───────────────────────────────────────────────────────
ipcMain.handle('backend:status',  () => backend.status())
ipcMain.handle('backend:start',   () => backend.start())
ipcMain.handle('backend:stop',    () => backend.stop())
ipcMain.handle('backend:restart', () => backend.restart())
ipcMain.handle('backend:getLogs', () => backend.getLogs())

// ─── File System ─────────────────────────────────────────────────────────────
ipcMain.handle('fs:readDir', (_, dirPath) => {
  try {
    const entries = readdirSync(dirPath, { withFileTypes: true })
    return entries.map(e => ({
      name: e.name,
      path: join(dirPath, e.name),
      isDirectory: e.isDirectory(),
      isFile: e.isFile()
    })).sort((a, b) => {
      if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1
      return a.name.localeCompare(b.name)
    })
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('fs:readFile', (_, filePath) => {
  try {
    return { content: readFileSync(filePath, 'utf-8') }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('fs:writeFile', (_, filePath, content) => {
  try {
    writeFileSync(filePath, content, 'utf-8')
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('fs:createFile', (_, filePath) => {
  try {
    writeFileSync(filePath, '', 'utf-8')
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('fs:createDir', (_, dirPath) => {
  try {
    mkdirSync(dirPath, { recursive: true })
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('fs:delete', (_, targetPath) => {
  try {
    rmSync(targetPath, { recursive: true, force: true })
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('fs:rename', (_, oldPath, newPath) => {
  try {
    renameSync(oldPath, newPath)
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('fs:exists', (_, filePath) => existsSync(filePath))

ipcMain.handle('fs:stat', (_, filePath) => {
  try {
    const s = statSync(filePath)
    return { size: s.size, mtime: s.mtimeMs, isDirectory: s.isDirectory(), isFile: s.isFile() }
  } catch (err) {
    return { error: err.message }
  }
})

// ─── Dialog ───────────────────────────────────────────────────────────────────
ipcMain.handle('dialog:openDirectory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory']
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('dialog:openFile', async (_, filters) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: filters || []
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('dialog:openFiles', async (_, filters) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    filters: filters || []
  })
  return result.canceled ? [] : result.filePaths
})

ipcMain.handle('dialog:saveFile', async (_, defaultPath) => {
  const result = await dialog.showSaveDialog(mainWindow, { defaultPath })
  return result.canceled ? null : result.filePath
})

ipcMain.handle('clipboard:saveImage', async (_, { dataUrl, name }) => {
  try {
    const raw = String(dataUrl || '')
    const match = raw.match(/^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/)
    if (!match) return { error: 'invalid_image_data' }
    const mime = match[1].toLowerCase()
    const base64 = match[2]
    const ext = (
      mime === 'image/png' ? 'png' :
      mime === 'image/jpeg' ? 'jpg' :
      mime === 'image/webp' ? 'webp' :
      mime === 'image/gif' ? 'gif' :
      mime === 'image/bmp' ? 'bmp' :
      'png'
    )
    const dir = join(os.tmpdir(), 'kendr-pasted-images')
    mkdirSync(dir, { recursive: true })
    const safeBase = String(name || 'pasted-image').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '') || 'pasted-image'
    const filePath = join(dir, `${safeBase}-${randomUUID()}.${ext}`)
    writeFileSync(filePath, Buffer.from(base64, 'base64'))
    return { path: filePath }
  } catch (err) {
    return { error: err.message }
  }
})

// ─── Git ─────────────────────────────────────────────────────────────────────
function runGit(cwd, args) {
  return new Promise((resolve, reject) => {
    exec(`git ${args}`, { cwd }, (err, stdout, stderr) => {
      if (err && !stdout) reject(new Error(stderr || err.message))
      else resolve(stdout.trim())
    })
  })
}

ipcMain.handle('git:status', async (_, cwd) => {
  try {
    const out = await runGit(cwd, 'status --porcelain=v1')
    const files = out.split('\n').filter(Boolean).map(line => ({
      status: line.slice(0, 2).trim(),
      path: line.slice(3).trim()
    }))
    const branch = await runGit(cwd, 'rev-parse --abbrev-ref HEAD').catch(() => 'unknown')
    return { files, branch }
  } catch (err) {
    return { error: err.message, files: [], branch: 'unknown' }
  }
})

ipcMain.handle('git:diff', async (_, cwd, filePath) => {
  try {
    const target = String(filePath || '').trim()
    const scopedPath = target
      ? (path.isAbsolute(target) ? path.relative(cwd, target) : target).replace(/\\/g, '/').replace(/"/g, '\\"')
      : ''
    const out = await runGit(cwd, scopedPath ? `diff HEAD -- "${scopedPath}"` : 'diff HEAD')
    return { diff: out }
  } catch (err) {
    return { error: err.message, diff: '' }
  }
})

ipcMain.handle('git:log', async (_, cwd, limit = 20) => {
  try {
    const out = await runGit(cwd, `log --oneline -${limit} --format="%H|%s|%an|%ar"`)
    const commits = out.split('\n').filter(Boolean).map(line => {
      const [hash, subject, author, date] = line.split('|')
      return { hash, subject, author, date }
    })
    return { commits }
  } catch (err) {
    return { error: err.message, commits: [] }
  }
})

ipcMain.handle('git:stage', async (_, cwd, files) => {
  try {
    const targets = Array.isArray(files) ? files.join(' ') : files
    await runGit(cwd, `add ${targets}`)
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('git:unstage', async (_, cwd, files) => {
  try {
    const targets = Array.isArray(files) ? files.join(' ') : files
    await runGit(cwd, `reset HEAD ${targets}`)
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('git:commit', async (_, cwd, message) => {
  try {
    await runGit(cwd, `commit -m "${message.replace(/"/g, '\\"')}"`)
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('git:push', async (_, cwd) => {
  try {
    const out = await runGit(cwd, 'push')
    return { ok: true, output: out }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('git:pull', async (_, cwd) => {
  try {
    const out = await runGit(cwd, 'pull')
    return { ok: true, output: out }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('git:branches', async (_, cwd) => {
  try {
    const out = await runGit(cwd, 'branch --format="%(refname:short)|%(upstream:short)"')
    const current = (await runGit(cwd, 'rev-parse --abbrev-ref HEAD').catch(() => ''))
    const branches = out.split('\n').filter(Boolean).map(line => {
      const [name, upstream] = line.split('|')
      return { name: name.trim(), upstream: upstream?.trim() || '', isCurrent: name.trim() === current }
    })
    return { branches }
  } catch (err) {
    return { error: err.message, branches: [] }
  }
})

ipcMain.handle('git:checkout', async (_, cwd, branch, create = false) => {
  try {
    await runGit(cwd, create ? `checkout -b "${branch}"` : `checkout "${branch}"`)
    return { ok: true }
  } catch (err) {
    return { error: err.message }
  }
})

// ─── PTY Terminal ─────────────────────────────────────────────────────────────
ipcMain.handle('pty:create', (_, opts = {}) => {
  if (!pty) return { error: 'node-pty not available' }
  const shell = opts.shell || (process.platform === 'win32' ? 'cmd.exe' : (process.env.SHELL || 'bash'))
  const cwd = opts.cwd || os.homedir()
  const id = Math.random().toString(36).slice(2)
  try {
    const proc = pty.spawn(shell, [], {
      name: 'xterm-256color',
      cols: opts.cols || 80,
      rows: opts.rows || 24,
      cwd,
      env: process.env
    })
    proc.onData(data => {
      mainWindow?.webContents.send(`pty:data:${id}`, data)
    })
    proc.onExit(() => {
      mainWindow?.webContents.send(`pty:exit:${id}`)
      ptyProcesses.delete(id)
    })
    ptyProcesses.set(id, proc)
    return { id }
  } catch (err) {
    return { error: err.message }
  }
})

ipcMain.handle('pty:write', (_, id, data) => {
  const proc = ptyProcesses.get(id)
  if (proc) { proc.write(data); return { ok: true } }
  return { error: 'PTY not found' }
})

ipcMain.handle('pty:resize', (_, id, cols, rows) => {
  const proc = ptyProcesses.get(id)
  if (proc) { proc.resize(cols, rows); return { ok: true } }
  return { error: 'PTY not found' }
})

ipcMain.handle('pty:kill', (_, id) => {
  const proc = ptyProcesses.get(id)
  if (proc) {
    try { proc.kill() } catch (_) {}
    ptyProcesses.delete(id)
    return { ok: true }
  }
  return { error: 'PTY not found' }
})

// ─── Shell execution ──────────────────────────────────────────────────────────
ipcMain.handle('shell:exec', (_, cmd, cwd) => {
  return new Promise(resolve => {
    exec(cmd, { cwd: cwd || os.homedir() }, (err, stdout, stderr) => {
      resolve({ stdout: stdout || '', stderr: stderr || '', code: err?.code || 0 })
    })
  })
})

ipcMain.handle('shell:openExternal', (_, url) => shell.openExternal(url))
