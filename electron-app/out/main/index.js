"use strict";
const electron = require("electron");
const crypto = require("crypto");
const path = require("path");
const fs = require("fs");
const child_process = require("child_process");
const os = require("os");
const http = require("http");
const electronUpdater = require("electron-updater");
class Store {
  constructor(opts = {}) {
    const dir = electron.app.getPath("userData");
    this._path = path.join(dir, "settings.json");
    this._defaults = opts.defaults || {};
    this._data = this._load();
  }
  _load() {
    try {
      const raw = fs.readFileSync(this._path, "utf-8");
      return { ...this._defaults, ...JSON.parse(raw) };
    } catch (_) {
      return { ...this._defaults };
    }
  }
  _save() {
    try {
      fs.mkdirSync(electron.app.getPath("userData"), { recursive: true });
      fs.writeFileSync(this._path, JSON.stringify(this._data, null, 2), "utf-8");
    } catch (_) {
    }
  }
  /** Get a value by dot-separated key, or the full store object if no key given. */
  get(key) {
    if (!key) return { ...this._data };
    return key.split(".").reduce((obj, k) => obj != null ? obj[k] : void 0, this._data);
  }
  /** Set a value. Accepts either (key, value) or a plain object to merge. */
  set(key, value) {
    if (typeof key === "object" && key !== null) {
      Object.assign(this._data, key);
    } else {
      const parts = String(key).split(".");
      let node = this._data;
      for (let i = 0; i < parts.length - 1; i++) {
        if (node[parts[i]] === void 0 || typeof node[parts[i]] !== "object") {
          node[parts[i]] = {};
        }
        node = node[parts[i]];
      }
      node[parts[parts.length - 1]] = value;
    }
    this._save();
  }
  /** Returns a shallow copy of all stored data. */
  get store() {
    return { ...this._data };
  }
}
const UI_PORT = 2151;
const GATEWAY_PORT = 8790;
const KENDR_HOME_DIR = path.join(os.homedir(), ".kendr");
const BACKEND_VERSION = (() => {
  try {
    const pkgPath = new URL(require("url").pathToFileURL(__filename).href).pathname.replace(/^\/([A-Z]:)/, "$1").replace(/[\\/]out[\\/]main[\\/]backend\.js$/, "/package.json");
    return JSON.parse(fs.readFileSync(pkgPath, "utf-8")).version;
  } catch {
    return "0.0.0";
  }
})();
class BackendManager {
  constructor(store2) {
    this.store = store2;
    this._proc = null;
    this._logs = [];
    this._status = {
      gateway: "stopped",
      // stopped | starting | running | error
      ui: "stopped",
      pid: null,
      kendrRoot: null,
      error: null,
      setup: null
      // null | { phase, pct, message }
    };
    this._listeners = [];
    this._healthTimer = null;
  }
  // ── Public API ──────────────────────────────────────────────────────────────
  status() {
    return { ...this._status, logs: [...this._logs] };
  }
  onChange(fn) {
    this._listeners.push(fn);
  }
  async startIfNeeded() {
    const [uiOk, gwOk] = await Promise.all([
      this._ping(UI_PORT),
      this._ping(GATEWAY_PORT)
    ]);
    if (uiOk && gwOk) {
      this._set({ gateway: "running", ui: "running" });
      this._startHealthWatch();
      return { ok: true, already: true };
    }
    if (uiOk || gwOk) {
      this._set({
        gateway: gwOk ? "running" : "starting",
        ui: uiOk ? "running" : "starting"
      });
      this._startHealthWatch();
    }
    return this.start();
  }
  async start() {
    if (this._status.gateway === "running" && this._status.ui === "running") {
      return { ok: true, already: true };
    }
    let command;
    let args;
    let cwd;
    let launchRoot;
    let extraEnv = {};
    const bundledExecutable = this._findBundledBackendExecutable();
    if (bundledExecutable) {
      command = bundledExecutable;
      args = [];
      cwd = path.dirname(bundledExecutable);
      launchRoot = cwd;
      this._log(`[backend] bundled executable: ${bundledExecutable}`);
    } else {
      const kendrRoot = this._findKendrRoot();
      if (!kendrRoot) {
        this._set({
          gateway: "error",
          ui: "error",
          error: "Cannot locate the packaged backend. Reinstall Kendr or set kendrRoot in Settings."
        });
        return { error: this._status.error };
      }
      let python;
      try {
        python = await this._resolvePython(kendrRoot);
      } catch (err) {
        this._set({ gateway: "error", ui: "error", error: err.message });
        return { error: err.message };
      }
      const gatewayScript = path.join(kendrRoot, "gateway_server.py");
      command = python;
      args = [gatewayScript];
      cwd = kendrRoot;
      launchRoot = kendrRoot;
      extraEnv = { PYTHONPATH: kendrRoot };
      this._log(`[backend] python: ${python}`);
      this._log(`[backend] script: ${gatewayScript}`);
    }
    this._set({ gateway: "starting", ui: "starting", error: null, kendrRoot: launchRoot, setup: null });
    return new Promise((resolve) => {
      try {
        this._proc = child_process.spawn(command, args, {
          cwd,
          env: {
            ...process.env,
            ...this._runtimeEnv(),
            KENDR_UI_ENABLED: "1",
            GATEWAY_PORT: String(GATEWAY_PORT),
            KENDR_UI_PORT: String(UI_PORT),
            PYTHONUNBUFFERED: "1",
            ...extraEnv,
            ...this._providerEnv()
          },
          stdio: ["ignore", "pipe", "pipe"],
          windowsHide: true
        });
        this._status.pid = this._proc.pid;
        let resolved = false;
        const tryResolve = () => {
          if (!resolved) {
            resolved = true;
            resolve({ ok: true });
          }
        };
        const handleLine = (line) => {
          this._log(line);
          if (line.includes("Gateway server running")) {
            this._set({ gateway: "running" });
            tryResolve();
          }
          if (line.includes("Kendr UI running") || line.includes("UI server") || line.includes("2151")) {
            this._set({ ui: "running" });
            tryResolve();
          }
        };
        let stdoutBuf = "", stderrBuf = "";
        this._proc.stdout?.on("data", (d) => {
          stdoutBuf += d.toString();
          const lines = stdoutBuf.split("\n");
          stdoutBuf = lines.pop();
          lines.forEach(handleLine);
        });
        this._proc.stderr?.on("data", (d) => {
          stderrBuf += d.toString();
          const lines = stderrBuf.split("\n");
          stderrBuf = lines.pop();
          lines.forEach((l) => this._log(`[stderr] ${l}`));
        });
        this._proc.on("error", (err) => {
          this._log(`[backend] spawn error: ${err.message}`);
          this._set({ gateway: "error", ui: "error", error: err.message, pid: null });
          if (!resolved) {
            resolved = true;
            resolve({ error: err.message });
          }
        });
        this._proc.on("exit", (code, signal) => {
          this._log(`[backend] exited  code=${code} signal=${signal}`);
          this._proc = null;
          this._status.pid = null;
          if (this._status.gateway !== "stopped") {
            this._set({
              gateway: code === 0 ? "stopped" : "error",
              ui: "stopped",
              error: code ? `Exited ${code}` : null
            });
          }
          this._stopHealthWatch();
        });
        setTimeout(async () => {
          const [uiOk, gwOk] = await Promise.all([this._ping(UI_PORT), this._ping(GATEWAY_PORT)]);
          if (uiOk) this._set({ ui: "running" });
          if (gwOk) this._set({ gateway: "running" });
          if (!resolved) {
            resolved = true;
            if (uiOk || gwOk) resolve({ ok: true });
            else {
              this._set({ ui: "error", gateway: "error", error: "Did not respond within 12 s" });
              resolve({ error: "Did not respond within 12 s" });
            }
          }
        }, 12e3);
        this._startHealthWatch();
      } catch (err) {
        this._set({ gateway: "error", ui: "error", error: err.message, pid: null });
        resolve({ error: err.message });
      }
    });
  }
  stop() {
    this._stopHealthWatch();
    if (this._proc) {
      try {
        this._proc.kill("SIGTERM");
      } catch (_) {
      }
      this._proc = null;
    }
    this._set({ gateway: "stopped", ui: "stopped", pid: null });
    return { ok: true };
  }
  async restart() {
    this.stop();
    await new Promise((r) => setTimeout(r, 600));
    return this.start();
  }
  getLogs() {
    return [...this._logs];
  }
  // ── Python / venv resolution ────────────────────────────────────────────────
  /**
   * Returns the python executable to use.
   * - Packaged app: creates/reuses a venv at ~/.kendr/venv
   * - Dev mode:     uses store.pythonPath or falls back to python/python3
   */
  async _resolvePython(kendrRoot) {
    if (!electron.app.isPackaged) {
      return this.store.get("pythonPath") || "python";
    }
    return this._ensureVenv(kendrRoot);
  }
  /**
   * Creates (or reuses) a venv at ~/.kendr/venv.
   * Installs the bundled kendr package the first time or after a version bump.
   * Pushes setup progress events so the renderer can show a setup screen.
   */
  async _ensureVenv(kendrRoot) {
    const kendrDir = path.join(os.homedir(), ".kendr");
    const venvDir = path.join(kendrDir, "venv");
    const venvMark = path.join(kendrDir, "venv-version");
    const isWin = process.platform === "win32";
    const venvPy = isWin ? path.join(venvDir, "Scripts", "python.exe") : path.join(venvDir, "bin", "python");
    const venvPip = isWin ? path.join(venvDir, "Scripts", "pip.exe") : path.join(venvDir, "bin", "pip");
    fs.mkdirSync(kendrDir, { recursive: true });
    const installedVersion = fs.existsSync(venvMark) ? fs.readFileSync(venvMark, "utf-8").trim() : "";
    const needsSetup = !fs.existsSync(venvPy) || installedVersion !== BACKEND_VERSION;
    if (!needsSetup) {
      this._log(`[venv] Using existing venv (v${installedVersion})`);
      return venvPy;
    }
    this._log(`[venv] Setting up venv at ${venvDir} (was: "${installedVersion}", need: "${BACKEND_VERSION}")`);
    this._set({ gateway: "starting", ui: "starting", setup: { phase: "setup", pct: 0, message: "Preparing Python environment…" } });
    const sysPython = await this._findSystemPython();
    if (!sysPython) {
      throw new Error(
        "Python 3.10+ is required but was not found.\nInstall from https://python.org/downloads and relaunch Kendr."
      );
    }
    this._log(`[venv] System python: ${sysPython}`);
    this._set({ setup: { phase: "venv", pct: 10, message: "Creating virtual environment…" } });
    await this._run(sysPython, ["-m", "venv", venvDir]);
    this._log(`[venv] venv created`);
    this._set({ setup: { phase: "pip", pct: 20, message: "Upgrading pip…" } });
    await this._run(venvPy, ["-m", "pip", "install", "--upgrade", "pip", "--quiet"]);
    this._set({ setup: { phase: "install", pct: 30, message: "Installing Kendr backend (this takes a few minutes on first run)…" } });
    this._log(`[venv] Installing from ${kendrRoot}`);
    await this._runStreaming(
      venvPip,
      ["install", kendrRoot, "--quiet", "--progress-bar", "off"],
      (line) => {
        this._log(`[pip] ${line}`);
        const cur = this._status.setup?.pct ?? 30;
        if (cur < 90) this._set({ setup: { ...this._status.setup, pct: cur + 1 } });
      }
    );
    fs.writeFileSync(venvMark, BACKEND_VERSION, "utf-8");
    this._set({ setup: { phase: "done", pct: 100, message: "Setup complete." } });
    this._log(`[venv] Setup complete — v${BACKEND_VERSION}`);
    return venvPy;
  }
  /** Find the first system python that is ≥ 3.10 */
  async _findSystemPython() {
    const candidates = process.platform === "win32" ? ["python", "python3", "py"] : ["python3", "python", "python3.12", "python3.11", "python3.10"];
    for (const cmd of candidates) {
      try {
        const ver = await this._runOutput(cmd, ["--version"]);
        const m = ver.match(/Python (\d+)\.(\d+)/);
        if (m && (parseInt(m[1]) > 3 || parseInt(m[1]) === 3 && parseInt(m[2]) >= 10)) {
          return cmd;
        }
      } catch {
      }
    }
    return null;
  }
  // ── Root discovery ──────────────────────────────────────────────────────────
  _findKendrRoot() {
    const saved = this.store.get("kendrRoot");
    if (saved && fs.existsSync(path.join(saved, "gateway_server.py"))) return saved;
    if (electron.app.isPackaged) {
      const bundled = path.join(process.resourcesPath, "kendr-backend-source");
      if (fs.existsSync(path.join(bundled, "gateway_server.py"))) {
        this.store.set("kendrRoot", bundled);
        return bundled;
      }
    }
    const anchors = [
      electron.app.getAppPath(),
      process.cwd(),
      new URL(require("url").pathToFileURL(__filename).href).pathname.replace(/^\/([A-Z]:)/, "$1").replace(/[\\/]out[\\/]main[\\/]backend\.js$/, "")
    ];
    for (const anchor of anchors) {
      for (let up = 0; up <= 4; up++) {
        let candidate = anchor;
        for (let i = 0; i < up; i++) candidate = path.join(candidate, "..");
        if (fs.existsSync(path.join(candidate, "gateway_server.py"))) {
          this.store.set("kendrRoot", candidate);
          return candidate;
        }
      }
    }
    return null;
  }
  _findBundledBackendExecutable() {
    if (!electron.app.isPackaged) return null;
    const bundleRoot = path.join(process.resourcesPath, "kendr-backend");
    const executable = process.platform === "win32" ? path.join(bundleRoot, "kendr-backend.exe") : path.join(bundleRoot, "kendr-backend");
    return fs.existsSync(executable) ? executable : null;
  }
  _runtimeEnv() {
    fs.mkdirSync(KENDR_HOME_DIR, { recursive: true });
    return {
      KENDR_HOME: KENDR_HOME_DIR,
      KENDR_DB_PATH: path.join(KENDR_HOME_DIR, "agent_workflow.sqlite3")
    };
  }
  // ── Internals ───────────────────────────────────────────────────────────────
  _set(patch) {
    Object.assign(this._status, patch);
    const snap = this.status();
    this._listeners.forEach((fn) => {
      try {
        fn(snap);
      } catch (_) {
      }
    });
  }
  _log(line) {
    if (!line?.trim()) return;
    this._logs.push(line);
    if (this._logs.length > 200) this._logs.shift();
  }
  _ping(port) {
    return new Promise((resolve) => {
      const req = http.get({ hostname: "127.0.0.1", port, path: "/health", timeout: 1500 }, (res) => {
        resolve(res.statusCode < 500);
      });
      req.on("error", () => resolve(false));
      req.on("timeout", () => {
        req.destroy();
        resolve(false);
      });
    });
  }
  _startHealthWatch() {
    this._stopHealthWatch();
    this._healthTimer = setInterval(async () => {
      const [uiOk, gwOk] = await Promise.all([this._ping(UI_PORT), this._ping(GATEWAY_PORT)]);
      let changed = false;
      if (uiOk && this._status.ui !== "running") {
        this._status.ui = "running";
        changed = true;
      }
      if (!uiOk && this._status.ui === "running") {
        this._status.ui = "error";
        changed = true;
      }
      if (gwOk && this._status.gateway !== "running") {
        this._status.gateway = "running";
        changed = true;
      }
      if (!gwOk && this._status.gateway === "running") {
        this._status.gateway = "error";
        changed = true;
      }
      if (changed) this._set({});
    }, 5e3);
  }
  _stopHealthWatch() {
    if (this._healthTimer) {
      clearInterval(this._healthTimer);
      this._healthTimer = null;
    }
  }
  _providerEnv() {
    return Object.fromEntries(
      [
        ["anthropicKey", "ANTHROPIC_API_KEY"],
        ["openaiKey", "OPENAI_API_KEY"],
        ["openaiOrgId", "OPENAI_ORG_ID"],
        ["googleKey", "GOOGLE_API_KEY"],
        ["xaiKey", "XAI_API_KEY"],
        ["hfToken", "HUGGINGFACEHUB_API_TOKEN"],
        ["tavilyKey", "TAVILY_API_KEY"],
        ["braveKey", "BRAVE_API_KEY"],
        ["serperKey", "SERPER_API_KEY"]
      ].map(([k, env]) => [env, String(this.store.get(k) || "").trim()]).filter(([, v]) => v)
    );
  }
  /** Run a command, resolve when it exits 0, reject otherwise. */
  _run(cmd, args) {
    return new Promise((resolve, reject) => {
      const child = child_process.spawn(cmd, args, { stdio: "ignore", windowsHide: true });
      child.on("error", reject);
      child.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)));
    });
  }
  /** Run a command and return its combined stdout+stderr as a string. */
  _runOutput(cmd, args) {
    return new Promise((resolve, reject) => {
      child_process.execFile(cmd, args, (err, stdout, stderr) => {
        if (err && !stdout && !stderr) return reject(err);
        resolve((stdout + stderr).trim());
      });
    });
  }
  /** Run a command and stream each output line to onLine(). */
  _runStreaming(cmd, args, onLine) {
    return new Promise((resolve, reject) => {
      const child = child_process.spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
      let buf = "";
      const handle = (chunk) => {
        buf += chunk.toString();
        const lines = buf.split("\n");
        buf = lines.pop();
        lines.forEach((l) => {
          try {
            onLine(l);
          } catch (_) {
          }
        });
      };
      child.stdout?.on("data", handle);
      child.stderr?.on("data", handle);
      child.on("error", reject);
      child.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)));
    });
  }
}
const {
  AppImageUpdater,
  DebUpdater,
  MacUpdater,
  NsisUpdater,
  PacmanUpdater,
  RpmUpdater
} = electronUpdater;
const UPDATE_SETTING_KEYS = /* @__PURE__ */ new Set([
  "updatesEnabled",
  "updateBaseUrl",
  "updateChannel",
  "autoDownloadUpdates",
  "autoInstallOnQuit",
  "allowPrereleaseUpdates",
  "updateCheckIntervalMinutes"
]);
const DEFAULT_INTERVAL_MINUTES = 240;
const MIN_INTERVAL_MINUTES = 15;
const MAX_INTERVAL_MINUTES = 1440;
function clampNumber(value, min, max, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.round(parsed)));
}
function normalizeUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw);
    if (!/^https?:$/.test(url.protocol)) return "";
    return url.toString().replace(/\/+$/, "");
  } catch (_) {
    return "";
  }
}
function errorMessage(error) {
  if (!error) return "Unknown update error.";
  if (typeof error === "string") return error;
  if (typeof error.message === "string" && error.message.trim()) return error.message.trim();
  return String(error);
}
function createLogger(scope = "updates") {
  return {
    info: (...args) => console.info(`[${scope}]`, ...args),
    warn: (...args) => console.warn(`[${scope}]`, ...args),
    error: (...args) => console.error(`[${scope}]`, ...args)
  };
}
function packagedUpdateConfigPath() {
  return path.join(process.resourcesPath, "app-update.yml");
}
function packagedUpdateConfigExists() {
  return electron.app.isPackaged && fs.existsSync(packagedUpdateConfigPath());
}
function packagedLinuxType() {
  try {
    const file = path.join(process.resourcesPath, "package-type");
    if (!fs.existsSync(file)) return "";
    return fs.readFileSync(file, "utf-8").trim().toLowerCase();
  } catch (_) {
    return "";
  }
}
function createPlatformUpdater(publishOptions) {
  if (process.platform === "win32") {
    return new NsisUpdater(publishOptions);
  }
  if (process.platform === "darwin") {
    return new MacUpdater(publishOptions);
  }
  switch (packagedLinuxType()) {
    case "deb":
      return new DebUpdater(publishOptions);
    case "rpm":
      return new RpmUpdater(publishOptions);
    case "pacman":
      return new PacmanUpdater(publishOptions);
    default:
      return new AppImageUpdater(publishOptions);
  }
}
class UpdateManager {
  constructor(store2, { getMainWindow } = {}) {
    this.store = store2;
    this.getMainWindow = typeof getMainWindow === "function" ? getMainWindow : () => null;
    this._listeners = [];
    this._timer = null;
    this._updater = null;
    this._configSignature = "";
    this._installPromptVersion = "";
    this._status = {
      supported: electron.app.isPackaged,
      enabled: store2.get("updatesEnabled") !== false,
      configured: false,
      invalidFeedUrl: false,
      status: electron.app.isPackaged ? "idle" : "unsupported",
      currentVersion: electron.app.getVersion(),
      availableVersion: null,
      downloadedVersion: null,
      checkedAt: null,
      progress: null,
      channel: "latest",
      feedUrl: "",
      feedSource: "none",
      autoDownload: store2.get("autoDownloadUpdates") !== false,
      autoInstallOnQuit: store2.get("autoInstallOnQuit") !== false,
      allowPrerelease: !!store2.get("allowPrereleaseUpdates"),
      intervalMinutes: clampNumber(
        store2.get("updateCheckIntervalMinutes"),
        MIN_INTERVAL_MINUTES,
        MAX_INTERVAL_MINUTES,
        DEFAULT_INTERVAL_MINUTES
      ),
      error: null,
      message: electron.app.isPackaged ? "Remote updates are idle." : "Automatic updates are available only in packaged Kendr builds."
    };
  }
  isUpdateSettingKey(key) {
    return UPDATE_SETTING_KEYS.has(String(key));
  }
  onChange(listener) {
    this._listeners.push(listener);
    return () => {
      this._listeners = this._listeners.filter((item) => item !== listener);
    };
  }
  status() {
    return {
      ...this._status,
      progress: this._status.progress ? { ...this._status.progress } : null
    };
  }
  init() {
    this.refreshConfig();
    if (this._canCheck()) {
      setTimeout(() => {
        this.checkForUpdates({ manual: false }).catch(() => {
        });
      }, 12e3);
    }
  }
  refreshConfig() {
    const config = this._readConfig();
    this._ensureUpdater(config);
    this._scheduleChecks(config);
    if (!config.supported) {
      this._setStatus({
        supported: false,
        enabled: config.enabled,
        configured: false,
        invalidFeedUrl: false,
        channel: config.channel,
        feedUrl: config.feedUrl,
        feedSource: config.feedSource,
        autoDownload: config.autoDownload,
        autoInstallOnQuit: config.autoInstallOnQuit,
        allowPrerelease: config.allowPrerelease,
        intervalMinutes: config.intervalMinutes,
        status: "unsupported",
        error: null,
        message: "Automatic updates are available only in packaged Kendr builds."
      });
      return this.status();
    }
    if (config.invalidFeedUrl) {
      this._setStatus({
        supported: true,
        enabled: config.enabled,
        configured: false,
        invalidFeedUrl: true,
        channel: config.channel,
        feedUrl: config.feedUrl,
        feedSource: config.feedSource,
        autoDownload: config.autoDownload,
        autoInstallOnQuit: config.autoInstallOnQuit,
        allowPrerelease: config.allowPrerelease,
        intervalMinutes: config.intervalMinutes,
        status: "disabled",
        error: null,
        message: "The Update Feed URL is invalid. Use a full http:// or https:// URL."
      });
      return this.status();
    }
    if (!config.enabled) {
      this._setStatus({
        supported: true,
        enabled: false,
        configured: config.configured,
        invalidFeedUrl: false,
        channel: config.channel,
        feedUrl: config.feedUrl,
        feedSource: config.feedSource,
        autoDownload: config.autoDownload,
        autoInstallOnQuit: config.autoInstallOnQuit,
        allowPrerelease: config.allowPrerelease,
        intervalMinutes: config.intervalMinutes,
        status: "disabled",
        error: null,
        message: "Remote updates are turned off."
      });
      return this.status();
    }
    if (!config.configured) {
      this._setStatus({
        supported: true,
        enabled: true,
        configured: false,
        invalidFeedUrl: false,
        channel: config.channel,
        feedUrl: config.feedUrl,
        feedSource: config.feedSource,
        autoDownload: config.autoDownload,
        autoInstallOnQuit: config.autoInstallOnQuit,
        allowPrerelease: config.allowPrerelease,
        intervalMinutes: config.intervalMinutes,
        status: "disabled",
        error: null,
        message: "No remote update feed is configured yet. Build releases with KENDR_UPDATE_URL or enter an Update Feed URL in Settings."
      });
      return this.status();
    }
    this._setStatus({
      supported: true,
      enabled: true,
      configured: true,
      invalidFeedUrl: false,
      channel: config.channel,
      feedUrl: config.feedUrl,
      feedSource: config.feedSource,
      autoDownload: config.autoDownload,
      autoInstallOnQuit: config.autoInstallOnQuit,
      allowPrerelease: config.allowPrerelease,
      intervalMinutes: config.intervalMinutes,
      ...this._status.status === "unsupported" || this._status.status === "disabled" ? {
        status: "idle",
        error: null,
        message: config.feedSource === "packaged" ? "Remote updates are configured from the packaged release feed." : "Remote updates are configured."
      } : {}
    });
    return this.status();
  }
  async checkForUpdates({ manual = true } = {}) {
    const config = this._readConfig();
    this._ensureUpdater(config);
    if (!this._canCheck(config)) return this.refreshConfig();
    if (!this._updater) return this.refreshConfig();
    try {
      await this._updater.checkForUpdates();
    } catch (error) {
      this._handleError(error, manual ? "Update check failed." : "Automatic update check failed.");
    }
    return this.status();
  }
  async downloadUpdate() {
    const config = this._readConfig();
    this._ensureUpdater(config);
    if (!this._canCheck(config)) return this.refreshConfig();
    if (!this._updater) return this.refreshConfig();
    try {
      await this._updater.downloadUpdate();
    } catch (error) {
      this._handleError(error, "Update download failed.");
    }
    return this.status();
  }
  quitAndInstall() {
    if (!this._updater || this._status.status !== "downloaded") return false;
    this._updater.quitAndInstall();
    return true;
  }
  _readConfig() {
    const rawFeedUrl = String(this.store.get("updateBaseUrl") || "").trim();
    const normalizedFeedUrl = normalizeUrl(rawFeedUrl);
    const envFeedUrl = normalizeUrl(process.env.KENDR_UPDATE_URL || "");
    const packagedConfig = packagedUpdateConfigExists();
    const invalidFeedUrl = Boolean(rawFeedUrl) && !normalizedFeedUrl;
    let feedSource = "none";
    let feedUrl = "";
    if (invalidFeedUrl) {
      feedSource = "invalid";
      feedUrl = rawFeedUrl;
    } else if (normalizedFeedUrl) {
      feedSource = "settings";
      feedUrl = normalizedFeedUrl;
    } else if (envFeedUrl) {
      feedSource = "env";
      feedUrl = envFeedUrl;
    } else if (packagedConfig) {
      feedSource = "packaged";
    }
    return {
      supported: electron.app.isPackaged,
      enabled: this.store.get("updatesEnabled") !== false,
      configured: !invalidFeedUrl && (packagedConfig || Boolean(feedUrl)),
      invalidFeedUrl,
      feedUrl,
      feedSource,
      channel: String(this.store.get("updateChannel") || process.env.KENDR_UPDATE_CHANNEL || "latest").trim() || "latest",
      autoDownload: this.store.get("autoDownloadUpdates") !== false,
      autoInstallOnQuit: this.store.get("autoInstallOnQuit") !== false,
      allowPrerelease: !!this.store.get("allowPrereleaseUpdates"),
      intervalMinutes: clampNumber(
        this.store.get("updateCheckIntervalMinutes"),
        MIN_INTERVAL_MINUTES,
        MAX_INTERVAL_MINUTES,
        DEFAULT_INTERVAL_MINUTES
      )
    };
  }
  _ensureUpdater(config) {
    const signature = JSON.stringify({
      supported: config.supported,
      configured: config.configured,
      invalidFeedUrl: config.invalidFeedUrl,
      feedUrl: config.feedUrl,
      channel: config.channel,
      autoDownload: config.autoDownload,
      autoInstallOnQuit: config.autoInstallOnQuit,
      allowPrerelease: config.allowPrerelease,
      feedSource: config.feedSource
    });
    if (!config.supported || !config.configured || config.invalidFeedUrl) {
      if (this._updater) {
        this._updater.removeAllListeners();
        this._updater = null;
        this._configSignature = "";
      }
      return;
    }
    if (this._configSignature === signature && this._updater) {
      return;
    }
    if (this._updater) {
      this._updater.removeAllListeners();
      this._updater = null;
    }
    const publishOptions = config.feedUrl ? {
      provider: "generic",
      url: config.feedUrl,
      channel: config.channel
    } : void 0;
    this._updater = createPlatformUpdater(publishOptions);
    this._updater.logger = createLogger("updater");
    this._updater.autoDownload = config.autoDownload;
    this._updater.autoInstallOnAppQuit = config.autoInstallOnQuit;
    this._updater.allowPrerelease = config.allowPrerelease;
    this._updater.allowDowngrade = false;
    this._updater.channel = config.channel;
    this._bindUpdaterEvents();
    this._configSignature = signature;
  }
  _bindUpdaterEvents() {
    if (!this._updater) return;
    this._updater.on("checking-for-update", () => {
      this._setStatus({
        status: "checking",
        error: null,
        progress: null,
        message: "Checking for a new Kendr release…"
      });
    });
    this._updater.on("update-available", (info) => {
      const version = String(info?.version || "").trim() || null;
      this._setStatus({
        status: this._status.autoDownload ? "downloading" : "available",
        availableVersion: version,
        downloadedVersion: null,
        checkedAt: (/* @__PURE__ */ new Date()).toISOString(),
        error: null,
        progress: this._status.autoDownload ? { percent: 0, transferred: 0, total: 0, bytesPerSecond: 0 } : null,
        message: this._status.autoDownload ? `Kendr ${version || "update"} is available. Downloading now…` : `Kendr ${version || "update"} is available to download.`
      });
    });
    this._updater.on("update-not-available", () => {
      this._setStatus({
        status: "up-to-date",
        availableVersion: null,
        downloadedVersion: null,
        checkedAt: (/* @__PURE__ */ new Date()).toISOString(),
        progress: null,
        error: null,
        message: `Kendr ${electron.app.getVersion()} is up to date.`
      });
    });
    this._updater.on("download-progress", (progress) => {
      const percent = Number.isFinite(progress?.percent) ? Math.max(0, Math.min(100, progress.percent)) : 0;
      this._setStatus({
        status: "downloading",
        progress: {
          percent,
          transferred: Number(progress?.transferred || 0),
          total: Number(progress?.total || 0),
          bytesPerSecond: Number(progress?.bytesPerSecond || 0)
        },
        error: null,
        message: `Downloading Kendr ${this._status.availableVersion || "update"} (${percent.toFixed(percent >= 10 ? 0 : 1)}%).`
      });
    });
    this._updater.on("update-downloaded", (event) => {
      const version = String(event?.version || this._status.availableVersion || "").trim() || null;
      this._setStatus({
        status: "downloaded",
        downloadedVersion: version,
        checkedAt: (/* @__PURE__ */ new Date()).toISOString(),
        progress: { percent: 100, transferred: 0, total: 0, bytesPerSecond: 0 },
        error: null,
        message: this._status.autoInstallOnQuit ? `Kendr ${version || "update"} is ready. It will install when the app quits, or you can restart now.` : `Kendr ${version || "update"} is ready. Restart the app to install it.`
      });
      this._promptToInstall(version);
    });
    this._updater.on("error", (error) => {
      this._handleError(error, "Update error.");
    });
  }
  _promptToInstall(version) {
    if (!version || this._installPromptVersion === version) return;
    this._installPromptVersion = version;
    const mainWindow2 = this.getMainWindow();
    electron.dialog.showMessageBox(mainWindow2 || void 0, {
      type: "info",
      buttons: ["Restart and Update", "Later"],
      defaultId: 0,
      cancelId: 1,
      title: "Kendr update ready",
      message: `Kendr ${version} has been downloaded.`,
      detail: this._status.autoInstallOnQuit ? "The update will install automatically when you quit Kendr. Restart now to apply it immediately." : "Restart Kendr now to install the downloaded update."
    }).then(({ response }) => {
      if (response === 0) this.quitAndInstall();
    }).catch(() => {
    });
  }
  _handleError(error, prefix) {
    const message = errorMessage(error);
    this._setStatus({
      status: "error",
      checkedAt: (/* @__PURE__ */ new Date()).toISOString(),
      progress: null,
      error: message,
      message: prefix ? `${prefix} ${message}` : message
    });
  }
  _canCheck(config = this._readConfig()) {
    return config.supported && config.enabled && config.configured && !config.invalidFeedUrl;
  }
  _scheduleChecks(config) {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    if (!this._canCheck(config)) return;
    this._timer = setInterval(() => {
      this.checkForUpdates({ manual: false }).catch(() => {
      });
    }, config.intervalMinutes * 60 * 1e3);
  }
  _setStatus(patch) {
    this._status = {
      ...this._status,
      ...patch,
      currentVersion: electron.app.getVersion(),
      progress: Object.prototype.hasOwnProperty.call(patch, "progress") ? patch.progress : this._status.progress
    };
    const snapshot = this.status();
    for (const listener of this._listeners) {
      try {
        listener(snapshot);
      } catch (_) {
      }
    }
  }
}
let pty;
try {
  pty = require("node-pty");
} catch (_) {
  pty = null;
}
const store = new Store({
  defaults: {
    backendUrl: "http://127.0.0.1:2151",
    gatewayUrl: "http://127.0.0.1:8790",
    pythonPath: "python",
    kendrRoot: "",
    // auto-detected; override in Settings if needed
    projectRoot: "",
    theme: "dark",
    fontSize: 14,
    tabSize: 2,
    fontFamily: "'Cascadia Code', 'Fira Code', monospace",
    gitName: os.userInfo().username,
    gitEmail: "",
    githubPat: "",
    autoStartBackend: true,
    updatesEnabled: true,
    updateBaseUrl: "",
    updateChannel: "latest",
    autoDownloadUpdates: true,
    autoInstallOnQuit: true,
    allowPrereleaseUpdates: false,
    updateCheckIntervalMinutes: 240,
    windowBounds: { width: 1400, height: 900 },
    sidebarWidth: 260,
    chatPanelWidth: 380,
    terminalHeight: 220,
    modelDownloadDir: path.join(os.homedir(), ".kendr", "models"),
    gpuLayers: 0,
    contextSize: 4096,
    threads: 4,
    chatHistoryRetentionDays: 14
  }
});
const backend = new BackendManager(store);
const updates = new UpdateManager(store, { getMainWindow: () => mainWindow });
const ptyProcesses = /* @__PURE__ */ new Map();
let mainWindow = null;
let rendererRecoveryAttempts = 0;
let rendererRecoveryResetTimer = null;
function resetRendererRecoveryBudgetSoon() {
  if (rendererRecoveryResetTimer) clearTimeout(rendererRecoveryResetTimer);
  rendererRecoveryResetTimer = setTimeout(() => {
    rendererRecoveryAttempts = 0;
    rendererRecoveryResetTimer = null;
  }, 3e4);
}
function reloadMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }
}
function createWindow() {
  const bounds = store.get("windowBounds");
  mainWindow = new electron.BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    minWidth: 800,
    minHeight: 600,
    frame: false,
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#161b22",
      symbolColor: "#7d8590",
      height: 32
    },
    backgroundColor: "#0d0f14",
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false
      // allow localhost API calls
    },
    icon: path.join(__dirname, "../../resources/icon.png")
  });
  mainWindow.on("resize", () => {
    store.set("windowBounds", mainWindow.getBounds());
  });
  mainWindow.on("close", () => {
    for (const [id, proc] of ptyProcesses) {
      try {
        proc.kill();
      } catch (_) {
      }
    }
    ptyProcesses.clear();
  });
  mainWindow.webContents.on("render-process-gone", (_, details) => {
    console.error("[renderer] process gone", details);
    if (rendererRecoveryAttempts >= 2) return;
    rendererRecoveryAttempts += 1;
    resetRendererRecoveryBudgetSoon();
    setTimeout(() => {
      reloadMainWindow();
    }, 300);
  });
  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }
}
electron.app.whenReady().then(async () => {
  createWindow();
  backend.onChange((status) => {
    mainWindow?.webContents.send("backend:status-push", status);
  });
  updates.onChange((status) => {
    mainWindow?.webContents.send("updates:status-push", status);
  });
  updates.init();
  if (store.get("autoStartBackend")) {
    setTimeout(() => backend.startIfNeeded().catch(() => {
    }), 800);
  } else {
    backend.startIfNeeded().catch(() => {
    });
  }
  electron.app.on("activate", () => {
    if (electron.BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});
electron.app.on("window-all-closed", () => {
  backend.stop();
  if (process.platform !== "darwin") electron.app.quit();
});
electron.ipcMain.handle("window:minimize", () => mainWindow?.minimize());
electron.ipcMain.handle("window:maximize", () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize();
  else mainWindow?.maximize();
});
electron.ipcMain.handle("window:close", () => mainWindow?.close());
electron.ipcMain.handle("window:isMaximized", () => mainWindow?.isMaximized() ?? false);
electron.ipcMain.handle("settings:get", (_, key) => key ? store.get(key) : store.store);
electron.ipcMain.handle("settings:set", (_, key, value) => {
  store.set(key, value);
  if (updates.isUpdateSettingKey(key)) {
    updates.refreshConfig();
  }
  return true;
});
electron.ipcMain.handle("settings:getAll", () => store.store);
electron.ipcMain.handle("updates:status", () => updates.status());
electron.ipcMain.handle("updates:check", () => updates.checkForUpdates({ manual: true }));
electron.ipcMain.handle("updates:download", () => updates.downloadUpdate());
electron.ipcMain.handle("updates:install", () => ({ ok: updates.quitAndInstall() }));
electron.ipcMain.handle("backend:status", () => backend.status());
electron.ipcMain.handle("backend:start", () => backend.start());
electron.ipcMain.handle("backend:stop", () => backend.stop());
electron.ipcMain.handle("backend:restart", () => backend.restart());
electron.ipcMain.handle("backend:getLogs", () => backend.getLogs());
electron.ipcMain.handle("fs:readDir", (_, dirPath) => {
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    return entries.map((e) => ({
      name: e.name,
      path: path.join(dirPath, e.name),
      isDirectory: e.isDirectory(),
      isFile: e.isFile()
    })).sort((a, b) => {
      if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("fs:readFile", (_, filePath) => {
  try {
    return { content: fs.readFileSync(filePath, "utf-8") };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("fs:writeFile", (_, filePath, content) => {
  try {
    fs.writeFileSync(filePath, content, "utf-8");
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("fs:createFile", (_, filePath) => {
  try {
    fs.writeFileSync(filePath, "", "utf-8");
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("fs:createDir", (_, dirPath) => {
  try {
    fs.mkdirSync(dirPath, { recursive: true });
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("fs:delete", (_, targetPath) => {
  try {
    fs.rmSync(targetPath, { recursive: true, force: true });
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("fs:rename", (_, oldPath, newPath) => {
  try {
    fs.renameSync(oldPath, newPath);
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("fs:exists", (_, filePath) => fs.existsSync(filePath));
electron.ipcMain.handle("fs:stat", (_, filePath) => {
  try {
    const s = fs.statSync(filePath);
    return { size: s.size, mtime: s.mtimeMs, isDirectory: s.isDirectory(), isFile: s.isFile() };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("dialog:openDirectory", async () => {
  const result = await electron.dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory"]
  });
  return result.canceled ? null : result.filePaths[0];
});
electron.ipcMain.handle("dialog:openFile", async (_, filters) => {
  const result = await electron.dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: filters || []
  });
  return result.canceled ? null : result.filePaths[0];
});
electron.ipcMain.handle("dialog:openFiles", async (_, filters) => {
  const result = await electron.dialog.showOpenDialog(mainWindow, {
    properties: ["openFile", "multiSelections"],
    filters: filters || []
  });
  return result.canceled ? [] : result.filePaths;
});
electron.ipcMain.handle("dialog:saveFile", async (_, defaultPath) => {
  const result = await electron.dialog.showSaveDialog(mainWindow, { defaultPath });
  return result.canceled ? null : result.filePath;
});
electron.ipcMain.handle("clipboard:saveImage", async (_, { dataUrl, name }) => {
  try {
    const raw = String(dataUrl || "");
    const match = raw.match(/^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/);
    if (!match) return { error: "invalid_image_data" };
    const mime = match[1].toLowerCase();
    const base64 = match[2];
    const ext = mime === "image/png" ? "png" : mime === "image/jpeg" ? "jpg" : mime === "image/webp" ? "webp" : mime === "image/gif" ? "gif" : mime === "image/bmp" ? "bmp" : "png";
    const dir = path.join(os.tmpdir(), "kendr-pasted-images");
    fs.mkdirSync(dir, { recursive: true });
    const safeBase = String(name || "pasted-image").replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "") || "pasted-image";
    const filePath = path.join(dir, `${safeBase}-${crypto.randomUUID()}.${ext}`);
    fs.writeFileSync(filePath, Buffer.from(base64, "base64"));
    return { path: filePath };
  } catch (err) {
    return { error: err.message };
  }
});
function runGit(cwd, args) {
  return new Promise((resolve, reject) => {
    child_process.exec(`git ${args}`, { cwd }, (err, stdout, stderr) => {
      if (err && !stdout) reject(new Error(stderr || err.message));
      else resolve(stdout.trim());
    });
  });
}
electron.ipcMain.handle("git:status", async (_, cwd) => {
  try {
    const out = await runGit(cwd, "status --porcelain=v1");
    const files = out.split("\n").filter(Boolean).map((line) => ({
      status: line.slice(0, 2).trim(),
      path: line.slice(3).trim()
    }));
    const branch = await runGit(cwd, "rev-parse --abbrev-ref HEAD").catch(() => "unknown");
    return { files, branch };
  } catch (err) {
    return { error: err.message, files: [], branch: "unknown" };
  }
});
electron.ipcMain.handle("git:diff", async (_, cwd, filePath) => {
  try {
    const target = String(filePath || "").trim();
    const scopedPath = target ? (path.isAbsolute(target) ? path.relative(cwd, target) : target).replace(/\\/g, "/").replace(/"/g, '\\"') : "";
    const out = await runGit(cwd, scopedPath ? `diff HEAD -- "${scopedPath}"` : "diff HEAD");
    return { diff: out };
  } catch (err) {
    return { error: err.message, diff: "" };
  }
});
electron.ipcMain.handle("git:log", async (_, cwd, limit = 20) => {
  try {
    const out = await runGit(cwd, `log --oneline -${limit} --format="%H|%s|%an|%ar"`);
    const commits = out.split("\n").filter(Boolean).map((line) => {
      const [hash, subject, author, date] = line.split("|");
      return { hash, subject, author, date };
    });
    return { commits };
  } catch (err) {
    return { error: err.message, commits: [] };
  }
});
electron.ipcMain.handle("git:stage", async (_, cwd, files) => {
  try {
    const targets = Array.isArray(files) ? files.join(" ") : files;
    await runGit(cwd, `add ${targets}`);
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("git:unstage", async (_, cwd, files) => {
  try {
    const targets = Array.isArray(files) ? files.join(" ") : files;
    await runGit(cwd, `reset HEAD ${targets}`);
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("git:commit", async (_, cwd, message) => {
  try {
    await runGit(cwd, `commit -m "${message.replace(/"/g, '\\"')}"`);
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("git:push", async (_, cwd) => {
  try {
    const out = await runGit(cwd, "push");
    return { ok: true, output: out };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("git:pull", async (_, cwd) => {
  try {
    const out = await runGit(cwd, "pull");
    return { ok: true, output: out };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("git:branches", async (_, cwd) => {
  try {
    const out = await runGit(cwd, 'branch --format="%(refname:short)|%(upstream:short)"');
    const current = await runGit(cwd, "rev-parse --abbrev-ref HEAD").catch(() => "");
    const branches = out.split("\n").filter(Boolean).map((line) => {
      const [name, upstream] = line.split("|");
      return { name: name.trim(), upstream: upstream?.trim() || "", isCurrent: name.trim() === current };
    });
    return { branches };
  } catch (err) {
    return { error: err.message, branches: [] };
  }
});
electron.ipcMain.handle("git:checkout", async (_, cwd, branch, create = false) => {
  try {
    await runGit(cwd, create ? `checkout -b "${branch}"` : `checkout "${branch}"`);
    return { ok: true };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("pty:create", (_, opts = {}) => {
  if (!pty) return { error: "node-pty not available" };
  const shell2 = opts.shell || (process.platform === "win32" ? "cmd.exe" : process.env.SHELL || "bash");
  const cwd = opts.cwd || os.homedir();
  const id = Math.random().toString(36).slice(2);
  try {
    const proc = pty.spawn(shell2, [], {
      name: "xterm-256color",
      cols: opts.cols || 80,
      rows: opts.rows || 24,
      cwd,
      env: process.env
    });
    proc.onData((data) => {
      mainWindow?.webContents.send(`pty:data:${id}`, data);
    });
    proc.onExit(() => {
      mainWindow?.webContents.send(`pty:exit:${id}`);
      ptyProcesses.delete(id);
    });
    ptyProcesses.set(id, proc);
    return { id };
  } catch (err) {
    return { error: err.message };
  }
});
electron.ipcMain.handle("pty:write", (_, id, data) => {
  const proc = ptyProcesses.get(id);
  if (proc) {
    proc.write(data);
    return { ok: true };
  }
  return { error: "PTY not found" };
});
electron.ipcMain.handle("pty:resize", (_, id, cols, rows) => {
  const proc = ptyProcesses.get(id);
  if (proc) {
    proc.resize(cols, rows);
    return { ok: true };
  }
  return { error: "PTY not found" };
});
electron.ipcMain.handle("pty:kill", (_, id) => {
  const proc = ptyProcesses.get(id);
  if (proc) {
    try {
      proc.kill();
    } catch (_2) {
    }
    ptyProcesses.delete(id);
    return { ok: true };
  }
  return { error: "PTY not found" };
});
electron.ipcMain.handle("shell:exec", (_, cmd, cwd) => {
  return new Promise((resolve) => {
    child_process.exec(cmd, { cwd: cwd || os.homedir() }, (err, stdout, stderr) => {
      resolve({ stdout: stdout || "", stderr: stderr || "", code: err?.code || 0 });
    });
  });
});
electron.ipcMain.handle("shell:openExternal", (_, url) => electron.shell.openExternal(url));
