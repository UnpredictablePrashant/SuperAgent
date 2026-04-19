import { app, dialog } from 'electron'
import { existsSync, readFileSync } from 'fs'
import { join } from 'path'
import electronUpdater from 'electron-updater'

const {
  AppImageUpdater,
  DebUpdater,
  MacUpdater,
  NsisUpdater,
  PacmanUpdater,
  RpmUpdater,
} = electronUpdater

const UPDATE_SETTING_KEYS = new Set([
  'updatesEnabled',
  'updateBaseUrl',
  'updateChannel',
  'autoDownloadUpdates',
  'autoInstallOnQuit',
  'allowPrereleaseUpdates',
  'updateCheckIntervalMinutes',
])

const DEFAULT_INTERVAL_MINUTES = 240
const MIN_INTERVAL_MINUTES = 15
const MAX_INTERVAL_MINUTES = 1440

function clampNumber(value, min, max, fallback) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, Math.round(parsed)))
}

function normalizeUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  try {
    const url = new URL(raw)
    if (!/^https?:$/.test(url.protocol)) return ''
    return url.toString().replace(/\/+$/, '')
  } catch (_) {
    return ''
  }
}

function errorMessage(error) {
  if (!error) return 'Unknown update error.'
  if (typeof error === 'string') return error
  if (typeof error.message === 'string' && error.message.trim()) return error.message.trim()
  return String(error)
}

function createLogger(scope = 'updates') {
  return {
    info: (...args) => console.info(`[${scope}]`, ...args),
    warn: (...args) => console.warn(`[${scope}]`, ...args),
    error: (...args) => console.error(`[${scope}]`, ...args),
  }
}

function packagedUpdateConfigPath() {
  return join(process.resourcesPath, 'app-update.yml')
}

function packagedUpdateConfigExists() {
  return app.isPackaged && existsSync(packagedUpdateConfigPath())
}

function packagedLinuxType() {
  try {
    const file = join(process.resourcesPath, 'package-type')
    if (!existsSync(file)) return ''
    return readFileSync(file, 'utf-8').trim().toLowerCase()
  } catch (_) {
    return ''
  }
}

function createPlatformUpdater(publishOptions) {
  if (process.platform === 'win32') {
    return new NsisUpdater(publishOptions)
  }
  if (process.platform === 'darwin') {
    return new MacUpdater(publishOptions)
  }

  switch (packagedLinuxType()) {
    case 'deb':
      return new DebUpdater(publishOptions)
    case 'rpm':
      return new RpmUpdater(publishOptions)
    case 'pacman':
      return new PacmanUpdater(publishOptions)
    default:
      return new AppImageUpdater(publishOptions)
  }
}

export class UpdateManager {
  constructor(store, { getMainWindow } = {}) {
    this.store = store
    this.getMainWindow = typeof getMainWindow === 'function' ? getMainWindow : () => null
    this._listeners = []
    this._timer = null
    this._updater = null
    this._configSignature = ''
    this._installPromptVersion = ''
    this._status = {
      supported: app.isPackaged,
      enabled: store.get('updatesEnabled') !== false,
      configured: false,
      invalidFeedUrl: false,
      status: app.isPackaged ? 'idle' : 'unsupported',
      currentVersion: app.getVersion(),
      availableVersion: null,
      downloadedVersion: null,
      checkedAt: null,
      progress: null,
      channel: 'latest',
      feedUrl: '',
      feedSource: 'none',
      autoDownload: store.get('autoDownloadUpdates') !== false,
      autoInstallOnQuit: store.get('autoInstallOnQuit') !== false,
      allowPrerelease: !!store.get('allowPrereleaseUpdates'),
      intervalMinutes: clampNumber(
        store.get('updateCheckIntervalMinutes'),
        MIN_INTERVAL_MINUTES,
        MAX_INTERVAL_MINUTES,
        DEFAULT_INTERVAL_MINUTES,
      ),
      error: null,
      message: app.isPackaged
        ? 'Remote updates are idle.'
        : 'Automatic updates are available only in packaged Kendr builds.',
    }
  }

  isUpdateSettingKey(key) {
    return UPDATE_SETTING_KEYS.has(String(key))
  }

  onChange(listener) {
    this._listeners.push(listener)
    return () => {
      this._listeners = this._listeners.filter((item) => item !== listener)
    }
  }

  status() {
    return {
      ...this._status,
      progress: this._status.progress ? { ...this._status.progress } : null,
    }
  }

  init() {
    this.refreshConfig()
    if (this._canCheck()) {
      setTimeout(() => {
        this.checkForUpdates({ manual: false }).catch(() => {})
      }, 12000)
    }
  }

  refreshConfig() {
    const config = this._readConfig()
    this._ensureUpdater(config)
    this._scheduleChecks(config)

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
        status: 'unsupported',
        error: null,
        message: 'Automatic updates are available only in packaged Kendr builds.',
      })
      return this.status()
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
        status: 'disabled',
        error: null,
        message: 'The Update Feed URL is invalid. Use a full http:// or https:// URL.',
      })
      return this.status()
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
        status: 'disabled',
        error: null,
        message: 'Remote updates are turned off.',
      })
      return this.status()
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
        status: 'disabled',
        error: null,
        message: 'No remote update feed is configured yet. Build releases with KENDR_UPDATE_URL or enter an Update Feed URL in Settings.',
      })
      return this.status()
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
      ...(this._status.status === 'unsupported' ||
      this._status.status === 'disabled'
        ? {
            status: 'idle',
            error: null,
            message:
              config.feedSource === 'packaged'
                ? 'Remote updates are configured from the packaged release feed.'
                : 'Remote updates are configured.',
          }
        : {}),
    })

    return this.status()
  }

  async checkForUpdates({ manual = true } = {}) {
    const config = this._readConfig()
    this._ensureUpdater(config)
    if (!this._canCheck(config)) return this.refreshConfig()
    if (!this._updater) return this.refreshConfig()

    try {
      await this._updater.checkForUpdates()
    } catch (error) {
      this._handleError(error, manual ? 'Update check failed.' : 'Automatic update check failed.')
    }
    return this.status()
  }

  async downloadUpdate() {
    const config = this._readConfig()
    this._ensureUpdater(config)
    if (!this._canCheck(config)) return this.refreshConfig()
    if (!this._updater) return this.refreshConfig()

    try {
      await this._updater.downloadUpdate()
    } catch (error) {
      this._handleError(error, 'Update download failed.')
    }
    return this.status()
  }

  quitAndInstall() {
    if (!this._updater || this._status.status !== 'downloaded') return false
    this._updater.quitAndInstall()
    return true
  }

  _readConfig() {
    const rawFeedUrl = String(this.store.get('updateBaseUrl') || '').trim()
    const normalizedFeedUrl = normalizeUrl(rawFeedUrl)
    const envFeedUrl = normalizeUrl(process.env.KENDR_UPDATE_URL || '')
    const packagedConfig = packagedUpdateConfigExists()
    const invalidFeedUrl = Boolean(rawFeedUrl) && !normalizedFeedUrl

    let feedSource = 'none'
    let feedUrl = ''
    if (invalidFeedUrl) {
      feedSource = 'invalid'
      feedUrl = rawFeedUrl
    } else if (normalizedFeedUrl) {
      feedSource = 'settings'
      feedUrl = normalizedFeedUrl
    } else if (envFeedUrl) {
      feedSource = 'env'
      feedUrl = envFeedUrl
    } else if (packagedConfig) {
      feedSource = 'packaged'
    }

    return {
      supported: app.isPackaged,
      enabled: this.store.get('updatesEnabled') !== false,
      configured: !invalidFeedUrl && (packagedConfig || Boolean(feedUrl)),
      invalidFeedUrl,
      feedUrl,
      feedSource,
      channel: String(this.store.get('updateChannel') || process.env.KENDR_UPDATE_CHANNEL || 'latest').trim() || 'latest',
      autoDownload: this.store.get('autoDownloadUpdates') !== false,
      autoInstallOnQuit: this.store.get('autoInstallOnQuit') !== false,
      allowPrerelease: !!this.store.get('allowPrereleaseUpdates'),
      intervalMinutes: clampNumber(
        this.store.get('updateCheckIntervalMinutes'),
        MIN_INTERVAL_MINUTES,
        MAX_INTERVAL_MINUTES,
        DEFAULT_INTERVAL_MINUTES,
      ),
    }
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
      feedSource: config.feedSource,
    })

    if (!config.supported || !config.configured || config.invalidFeedUrl) {
      if (this._updater) {
        this._updater.removeAllListeners()
        this._updater = null
        this._configSignature = ''
      }
      return
    }

    if (this._configSignature === signature && this._updater) {
      return
    }

    if (this._updater) {
      this._updater.removeAllListeners()
      this._updater = null
    }

    const publishOptions = config.feedUrl
      ? {
          provider: 'generic',
          url: config.feedUrl,
          channel: config.channel,
        }
      : undefined

    this._updater = createPlatformUpdater(publishOptions)
    this._updater.logger = createLogger('updater')
    this._updater.autoDownload = config.autoDownload
    this._updater.autoInstallOnAppQuit = config.autoInstallOnQuit
    this._updater.allowPrerelease = config.allowPrerelease
    this._updater.allowDowngrade = false
    this._updater.channel = config.channel
    this._bindUpdaterEvents()
    this._configSignature = signature
  }

  _bindUpdaterEvents() {
    if (!this._updater) return

    this._updater.on('checking-for-update', () => {
      this._setStatus({
        status: 'checking',
        error: null,
        progress: null,
        message: 'Checking for a new Kendr release…',
      })
    })

    this._updater.on('update-available', (info) => {
      const version = String(info?.version || '').trim() || null
      this._setStatus({
        status: this._status.autoDownload ? 'downloading' : 'available',
        availableVersion: version,
        downloadedVersion: null,
        checkedAt: new Date().toISOString(),
        error: null,
        progress: this._status.autoDownload ? { percent: 0, transferred: 0, total: 0, bytesPerSecond: 0 } : null,
        message: this._status.autoDownload
          ? `Kendr ${version || 'update'} is available. Downloading now…`
          : `Kendr ${version || 'update'} is available to download.`,
      })
    })

    this._updater.on('update-not-available', () => {
      this._setStatus({
        status: 'up-to-date',
        availableVersion: null,
        downloadedVersion: null,
        checkedAt: new Date().toISOString(),
        progress: null,
        error: null,
        message: `Kendr ${app.getVersion()} is up to date.`,
      })
    })

    this._updater.on('download-progress', (progress) => {
      const percent = Number.isFinite(progress?.percent) ? Math.max(0, Math.min(100, progress.percent)) : 0
      this._setStatus({
        status: 'downloading',
        progress: {
          percent,
          transferred: Number(progress?.transferred || 0),
          total: Number(progress?.total || 0),
          bytesPerSecond: Number(progress?.bytesPerSecond || 0),
        },
        error: null,
        message: `Downloading Kendr ${this._status.availableVersion || 'update'} (${percent.toFixed(percent >= 10 ? 0 : 1)}%).`,
      })
    })

    this._updater.on('update-downloaded', (event) => {
      const version = String(event?.version || this._status.availableVersion || '').trim() || null
      this._setStatus({
        status: 'downloaded',
        downloadedVersion: version,
        checkedAt: new Date().toISOString(),
        progress: { percent: 100, transferred: 0, total: 0, bytesPerSecond: 0 },
        error: null,
        message: this._status.autoInstallOnQuit
          ? `Kendr ${version || 'update'} is ready. It will install when the app quits, or you can restart now.`
          : `Kendr ${version || 'update'} is ready. Restart the app to install it.`,
      })
      this._promptToInstall(version)
    })

    this._updater.on('error', (error) => {
      this._handleError(error, 'Update error.')
    })
  }

  _promptToInstall(version) {
    if (!version || this._installPromptVersion === version) return
    this._installPromptVersion = version
    const mainWindow = this.getMainWindow()
    dialog.showMessageBox(mainWindow || undefined, {
      type: 'info',
      buttons: ['Restart and Update', 'Later'],
      defaultId: 0,
      cancelId: 1,
      title: 'Kendr update ready',
      message: `Kendr ${version} has been downloaded.`,
      detail: this._status.autoInstallOnQuit
        ? 'The update will install automatically when you quit Kendr. Restart now to apply it immediately.'
        : 'Restart Kendr now to install the downloaded update.',
    }).then(({ response }) => {
      if (response === 0) this.quitAndInstall()
    }).catch(() => {})
  }

  _handleError(error, prefix) {
    const message = errorMessage(error)
    this._setStatus({
      status: 'error',
      checkedAt: new Date().toISOString(),
      progress: null,
      error: message,
      message: prefix ? `${prefix} ${message}` : message,
    })
  }

  _canCheck(config = this._readConfig()) {
    return config.supported && config.enabled && config.configured && !config.invalidFeedUrl
  }

  _scheduleChecks(config) {
    if (this._timer) {
      clearInterval(this._timer)
      this._timer = null
    }
    if (!this._canCheck(config)) return
    this._timer = setInterval(() => {
      this.checkForUpdates({ manual: false }).catch(() => {})
    }, config.intervalMinutes * 60 * 1000)
  }

  _setStatus(patch) {
    this._status = {
      ...this._status,
      ...patch,
      currentVersion: app.getVersion(),
      progress: Object.prototype.hasOwnProperty.call(patch, 'progress')
        ? patch.progress
        : this._status.progress,
    }
    const snapshot = this.status()
    for (const listener of this._listeners) {
      try {
        listener(snapshot)
      } catch (_) {}
    }
  }
}
