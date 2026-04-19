import React, { createContext, useContext, useReducer, useEffect, useCallback } from 'react'

const AppContext = createContext(null)
const MODEL_INVENTORY_TTL_MS = 60 * 1000
const OLLAMA_MODELS_TTL_MS = 30 * 1000

function normalizeView(view) {
  switch (view) {
    case 'chat':
      return 'studio'
    case 'files':
    case 'git':
    case 'project':
      return 'developer'
    case 'agents':
      return 'build'
    case 'mcp':
      return 'integrations'
    case 'skills':
      return 'marketplace'
    case 'models':
    case 'docs':
      return 'settings'
    case 'orchestration':
      return 'runs'
    default:
      return view || 'home'
  }
}

const initialState = {
  // App mode
  appMode: (() => { try { return localStorage.getItem('kendr:appMode') || 'studio' } catch { return 'studio' } })(),
  selectedModel: (() => { try { return localStorage.getItem('kendr:selectedModel') || null } catch { return null } })(),

  // Views & panels
  activeView: 'studio',
  sidebarOpen: true,
  chatOpen: true,
  terminalOpen: false,

  // Editor tabs
  openTabs: [],               // [{path, name, language, modified}]
  activeTabPath: null,

  // Project
  projectRoot: '',

  // Backend services (gateway :8790 + UI :2151)
  backendStatus: 'connecting',  // legacy derived field used by other components
  backendServices: { ui: 'connecting', gateway: 'connecting', pid: null, kendrRoot: null, error: null },
  backendUrl:  'http://127.0.0.1:2151',
  gatewayUrl:  'http://127.0.0.1:8790',

  // Chat
  messages: [],               // [{id, role, content, status, runId, agents}]
  activeRunId: null,
  streaming: false,

  // Runs
  runs: [],
  activityFeed: [],

  // Git
  gitStatus: null,
  gitBranch: 'main',

  // Command palette
  commandPaletteOpen: false,

  // Settings (loaded from electron-store)
  settings: {},
  updateStatus: {
    supported: false,
    enabled: true,
    configured: false,
    invalidFeedUrl: false,
    status: 'idle',
    currentVersion: null,
    availableVersion: null,
    downloadedVersion: null,
    checkedAt: null,
    progress: null,
    channel: 'latest',
    feedUrl: '',
    feedSource: 'none',
    autoDownload: true,
    autoInstallOnQuit: true,
    allowPrerelease: false,
    intervalMinutes: 240,
    error: null,
    message: '',
  },

  // Shared model/provider inventory cache
  modelInventory: null,
  modelInventoryLoading: false,
  modelInventoryError: false,
  modelInventoryFetchedAt: 0,
  ollamaModels: [],
  ollamaLoading: false,
  ollamaError: false,
  ollamaFetchedAt: 0,

  // Project mode
  editorSelection: null,   // {path, text, startLine, startCol, endLine, endCol}
  terminalCmd: null,       // {id, command, cwd} — consumed by TerminalPanel
  composerOpen: true,      // AI Composer visibility in project mode
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_VIEW': return { ...state, activeView: normalizeView(action.view) }
    case 'TOGGLE_SIDEBAR': return { ...state, sidebarOpen: !state.sidebarOpen }
    case 'SET_SIDEBAR': return { ...state, sidebarOpen: action.open }
    case 'TOGGLE_CHAT': return { ...state, chatOpen: !state.chatOpen }
    case 'TOGGLE_TERMINAL': return { ...state, terminalOpen: !state.terminalOpen }
    case 'SET_TERMINAL': return { ...state, terminalOpen: action.open }

    case 'OPEN_TAB': {
      const exists = state.openTabs.find(t => t.path === action.tab.path)
      if (exists) return { ...state, activeTabPath: action.tab.path }
      return {
        ...state,
        openTabs: [...state.openTabs, action.tab],
        activeTabPath: action.tab.path
      }
    }
    case 'CLOSE_TAB': {
      const tabs = state.openTabs.filter(t => t.path !== action.path)
      let active = state.activeTabPath
      if (active === action.path) {
        const idx = state.openTabs.findIndex(t => t.path === action.path)
        active = tabs[Math.min(idx, tabs.length - 1)]?.path || null
      }
      return { ...state, openTabs: tabs, activeTabPath: active }
    }
    case 'SET_ACTIVE_TAB': return { ...state, activeTabPath: action.path }
    case 'MARK_TAB_MODIFIED': {
      const tabs = state.openTabs.map(t =>
        t.path === action.path ? { ...t, modified: action.modified } : t
      )
      return { ...state, openTabs: tabs }
    }

    case 'SET_PROJECT_ROOT': return { ...state, projectRoot: action.root }
    case 'SET_BACKEND_STATUS': return { ...state, backendStatus: action.status }
    case 'SET_BACKEND_URL': return { ...state, backendUrl: action.url }
    case 'SET_BACKEND_SERVICES': {
      const svcs = { ...state.backendServices, ...action.services }
      // Derive the legacy backendStatus from both service states
      const derived =
        svcs.ui === 'running' && svcs.gateway === 'running' ? 'running' :
        svcs.ui === 'starting' || svcs.gateway === 'starting' ? 'starting' :
        svcs.ui === 'error'   || svcs.gateway === 'error'    ? 'error' : 'stopped'
      return { ...state, backendServices: svcs, backendStatus: derived }
    }

    case 'ADD_MESSAGE': return { ...state, messages: [...state.messages, action.message] }
    case 'UPDATE_MESSAGE': return {
      ...state,
      messages: state.messages.map(m => m.id === action.id ? { ...m, ...action.updates } : m)
    }
    case 'SET_MESSAGES': return { ...state, messages: action.messages }
    case 'CLEAR_MESSAGES': return { ...state, messages: [] }
    case 'SET_STREAMING': return { ...state, streaming: action.streaming }
    case 'SET_ACTIVE_RUN': return { ...state, activeRunId: action.runId }
    case 'SET_RUNS': return { ...state, runs: action.runs }
    case 'UPSERT_ACTIVITY_ENTRY': {
      const entry = action.entry
      if (!entry?.id) return state
      const existing = state.activityFeed.filter((item) => item.id !== entry.id)
      return {
        ...state,
        activityFeed: [entry, ...existing].slice(0, 40),
      }
    }
    case 'REMOVE_ACTIVITY_ENTRIES': {
      const ids = new Set(Array.isArray(action.ids) ? action.ids : [])
      if (!ids.size) return state
      return {
        ...state,
        activityFeed: state.activityFeed.filter((item) => !ids.has(item.id)),
      }
    }
    case 'CLEAR_ACTIVITY_FEED':
      return { ...state, activityFeed: [] }

    case 'SET_GIT_STATUS': return { ...state, gitStatus: action.status, gitBranch: action.branch || state.gitBranch }
    case 'TOGGLE_COMMAND_PALETTE': return { ...state, commandPaletteOpen: !state.commandPaletteOpen }
    case 'SET_COMMAND_PALETTE': return { ...state, commandPaletteOpen: action.open }
    case 'SET_SETTINGS': return { ...state, settings: { ...state.settings, ...action.settings } }
    case 'SET_UPDATE_STATUS':
      return { ...state, updateStatus: { ...state.updateStatus, ...action.status } }
    case 'SET_MODEL_INVENTORY_LOADING':
      return { ...state, modelInventoryLoading: action.loading, modelInventoryError: action.loading ? false : state.modelInventoryError }
    case 'SET_MODEL_INVENTORY':
      return {
        ...state,
        modelInventory: action.inventory,
        modelInventoryLoading: false,
        modelInventoryError: false,
        modelInventoryFetchedAt: action.fetchedAt || Date.now(),
      }
    case 'SET_MODEL_INVENTORY_ERROR':
      return { ...state, modelInventoryLoading: false, modelInventoryError: true, modelInventoryFetchedAt: action.fetchedAt || state.modelInventoryFetchedAt }
    case 'SET_OLLAMA_LOADING':
      return { ...state, ollamaLoading: action.loading, ollamaError: action.loading ? false : state.ollamaError }
    case 'SET_OLLAMA_MODELS':
      return {
        ...state,
        ollamaModels: Array.isArray(action.models) ? action.models : [],
        ollamaLoading: false,
        ollamaError: false,
        ollamaFetchedAt: action.fetchedAt || Date.now(),
      }
    case 'SET_OLLAMA_ERROR':
      return { ...state, ollamaLoading: false, ollamaError: true, ollamaFetchedAt: action.fetchedAt || state.ollamaFetchedAt }

    case 'SET_EDITOR_SELECTION': return { ...state, editorSelection: action.selection }
    case 'RUN_COMMAND': return { ...state, terminalOpen: true, terminalCmd: { id: Date.now(), ...action.cmd } }
    case 'CLEAR_TERMINAL_CMD': return { ...state, terminalCmd: null }
    case 'TOGGLE_COMPOSER': return { ...state, composerOpen: !state.composerOpen }

    case 'SET_APP_MODE': {
      try { localStorage.setItem('kendr:appMode', action.mode) } catch {}
      return { ...state, appMode: action.mode }
    }
    case 'SET_MODEL': {
      try {
        if (action.model) localStorage.setItem('kendr:selectedModel', action.model)
        else localStorage.removeItem('kendr:selectedModel')
      } catch {}
      return { ...state, selectedModel: action.model }
    }

    default: return state
  }
}

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  // Load settings from electron-store on mount
  useEffect(() => {
    const api = window.kendrAPI
    if (!api) return
    api.settings.getAll().then(settings => {
      dispatch({ type: 'SET_SETTINGS', settings })
      if (settings.backendUrl) dispatch({ type: 'SET_BACKEND_URL', url: settings.backendUrl })
      if (settings.projectRoot) dispatch({ type: 'SET_PROJECT_ROOT', root: settings.projectRoot })
    })
  }, [])

  const refreshModelInventory = useCallback(async (force = false) => {
    const backendReady = state.backendStatus === 'running' || state.backendStatus === 'connecting'
    if (!backendReady) return null
    const isFresh = state.modelInventory && (Date.now() - state.modelInventoryFetchedAt) < MODEL_INVENTORY_TTL_MS
    if (!force && (state.modelInventoryLoading || isFresh)) return state.modelInventory
    dispatch({ type: 'SET_MODEL_INVENTORY_LOADING', loading: true })
    try {
      const resp = await fetch(`${state.backendUrl || 'http://127.0.0.1:2151'}/api/models`)
      if (!resp.ok) throw new Error(`inventory_${resp.status}`)
      const data = await resp.json()
      dispatch({ type: 'SET_MODEL_INVENTORY', inventory: data || null, fetchedAt: Date.now() })
      return data || null
    } catch (_) {
      dispatch({ type: 'SET_MODEL_INVENTORY_ERROR', fetchedAt: Date.now() })
      return null
    }
  }, [state.backendStatus, state.backendUrl, state.modelInventory, state.modelInventoryFetchedAt, state.modelInventoryLoading])

  const refreshOllamaModels = useCallback(async (force = false) => {
    const backendReady = state.backendStatus === 'running' || state.backendStatus === 'connecting'
    if (!backendReady) return []
    const isFresh = Array.isArray(state.ollamaModels) && state.ollamaFetchedAt && (Date.now() - state.ollamaFetchedAt) < OLLAMA_MODELS_TTL_MS
    if (!force && (state.ollamaLoading || isFresh)) return state.ollamaModels
    dispatch({ type: 'SET_OLLAMA_LOADING', loading: true })
    try {
      const resp = await fetch(`${state.backendUrl || 'http://127.0.0.1:2151'}/api/models/ollama`)
      if (!resp.ok) throw new Error(`ollama_${resp.status}`)
      const data = await resp.json()
      const models = Array.isArray(data.models) ? data.models : []
      dispatch({ type: 'SET_OLLAMA_MODELS', models, fetchedAt: Date.now() })
      return models
    } catch (_) {
      dispatch({ type: 'SET_OLLAMA_ERROR', fetchedAt: Date.now() })
      return []
    }
  }, [state.backendStatus, state.backendUrl, state.ollamaFetchedAt, state.ollamaLoading, state.ollamaModels])

  const refreshModelData = useCallback(async (force = false) => {
    await Promise.all([refreshModelInventory(force), refreshOllamaModels(force)])
  }, [refreshModelInventory, refreshOllamaModels])

  // Fetch model inventory once when the backend first becomes available — no polling.
  const modelsFetchedRef = React.useRef(false)
  useEffect(() => {
    if (state.backendStatus !== 'running' && state.backendStatus !== 'connecting') return
    if (modelsFetchedRef.current) return
    modelsFetchedRef.current = true
    refreshModelData(false)
  }, [refreshModelData, state.backendStatus])

  // Subscribe to real-time backend status pushed from the main process.
  // No polling needed — the BackendManager pushes on every state change.
  useEffect(() => {
    const api = window.kendrAPI
    if (!api) return
    // Fetch initial snapshot
    api.backend.status().then(status => {
      dispatch({ type: 'SET_BACKEND_SERVICES', services: status })
    })
    // Live updates via IPC
    const unsub = api.backend.onStatusChange((status) => {
      dispatch({ type: 'SET_BACKEND_SERVICES', services: status })
    })
    return () => { try { unsub?.() } catch (_) {} }
  }, [])

  useEffect(() => {
    const api = window.kendrAPI
    if (!api?.updates) return
    api.updates.status().then((status) => {
      if (status) dispatch({ type: 'SET_UPDATE_STATUS', status })
    })
    const unsub = api.updates.onStatusChange((status) => {
      dispatch({ type: 'SET_UPDATE_STATUS', status })
    })
    return () => { try { unsub?.() } catch (_) {} }
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'P') {
        e.preventDefault()
        dispatch({ type: 'TOGGLE_COMMAND_PALETTE' })
      }
      if ((e.ctrlKey || e.metaKey) && e.key === '`') {
        e.preventDefault()
        dispatch({ type: 'TOGGLE_TERMINAL' })
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault()
        dispatch({ type: 'TOGGLE_SIDEBAR' })
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'J') {
        e.preventDefault()
        dispatch({ type: 'SET_VIEW', view: 'developer' })
      }
      if (e.key === 'Escape') {
        dispatch({ type: 'SET_COMMAND_PALETTE', open: false })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const openFile = useCallback(async (filePath) => {
    const api = window.kendrAPI
    if (!api) return
    const ext = filePath.split('.').pop()?.toLowerCase() || ''
    const langMap = {
      js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
      py: 'python', json: 'json', md: 'markdown', html: 'html', css: 'css',
      yml: 'yaml', yaml: 'yaml', sh: 'shell', bash: 'shell', txt: 'plaintext',
      rs: 'rust', go: 'go', java: 'java', cpp: 'cpp', c: 'c', rb: 'ruby',
      php: 'php', swift: 'swift', kt: 'kotlin', sql: 'sql', xml: 'xml',
      toml: 'toml', ini: 'ini', env: 'plaintext', dockerfile: 'dockerfile'
    }
    const language = langMap[ext] || 'plaintext'
    const { content, error } = await api.fs.readFile(filePath)
    if (error) return
    const name = filePath.split(/[\\/]/).pop()
    dispatch({ type: 'OPEN_TAB', tab: { path: filePath, name, language, content, modified: false } })
  }, [])

  return (
    <AppContext.Provider value={{ state, dispatch, openFile, refreshModelInventory, refreshOllamaModels, refreshModelData }}>
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside AppProvider')
  return ctx
}
