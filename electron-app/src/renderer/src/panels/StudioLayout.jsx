import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useApp } from '../contexts/AppContext'
import ChatPanel from './ChatPanel'
import { resolveAgentCapability } from '../lib/modelSelection'

// ─── Cloud model catalogue ────────────────────────────────────────────────────
const PROVIDER_ORDER = ['anthropic', 'openai', 'google', 'xai']

const CLOUD_MODELS = [
  { id: 'anthropic/claude-opus-4-6',    label: 'Claude Opus 4.6',    provider: 'anthropic' },
  { id: 'anthropic/claude-sonnet-4-6',  label: 'Claude Sonnet 4.6',  provider: 'anthropic' },
  { id: 'anthropic/claude-haiku-4-5',   label: 'Claude Haiku 4.5',   provider: 'anthropic' },
  { id: 'openai/gpt-4o',               label: 'GPT-4o',             provider: 'openai' },
  { id: 'openai/gpt-4o-mini',          label: 'GPT-4o mini',        provider: 'openai' },
  { id: 'openai/gpt-4-turbo',          label: 'GPT-4 Turbo',        provider: 'openai' },
  { id: 'google/gemini-2.0-flash',      label: 'Gemini 2.0 Flash',   provider: 'google' },
  { id: 'google/gemini-2.5-pro',        label: 'Gemini 2.5 Pro',     provider: 'google' },
  { id: 'google/gemini-1.5-pro',        label: 'Gemini 1.5 Pro',     provider: 'google' },
  { id: 'xai/grok-4',                               label: 'Grok 4',                   provider: 'xai' },
  { id: 'xai/grok-4.20-beta-latest-non-reasoning', label: 'Grok 4.20',                provider: 'xai' },
  { id: 'xai/grok-4-1-fast-reasoning',              label: 'Grok 4.1 Fast Reasoning',  provider: 'xai' },
]

const PROVIDER_META = {
  anthropic: { label: 'Anthropic', settingsKey: 'anthropicKey' },
  openai:    { label: 'OpenAI',    settingsKey: 'openaiKey' },
  google:    { label: 'Google AI', settingsKey: 'googleKey' },
  xai:       { label: 'xAI / Grok', settingsKey: 'xaiKey' },
}

// ─── Session helpers (operate directly on localStorage) ──────────────────────
const SESSIONS_KEY     = 'kendr_sessions_v1'
const CURRENT_HIST_KEY = 'kendr_chat_history_v1'

function lsGet(key) {
  try { return JSON.parse(localStorage.getItem(key)) } catch { return null }
}
function lsSet(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)) } catch {}
}

function readSessions(settings) {
  const all = lsGet(SESSIONS_KEY) || []
  const days = settings?.chatHistoryRetentionDays ?? 14
  if (!days || days <= 0) return all.slice().reverse()
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000
  return all.filter(s => new Date(s.updatedAt || s.createdAt).getTime() >= cutoff).reverse()
}

function saveCurrentAsSession(chatId) {
  const messages = lsGet(CURRENT_HIST_KEY) || []
  if (!messages.length) return
  const first = messages.find(m => m.role === 'user')
  const title = String(first?.content || '').slice(0, 60) || 'New conversation'
  const all = lsGet(SESSIONS_KEY) || []
  const session = {
    id: chatId,
    title,
    createdAt: String(messages[0]?.ts || new Date().toISOString()),
    updatedAt: new Date().toISOString(),
    messages,
  }
  lsSet(SESSIONS_KEY, [...all.filter(s => s.id !== chatId), session].slice(-100))
}

function sessionRelTime(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 60000) return 'just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  const d = new Date(dateStr)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// ─── StudioLayout ─────────────────────────────────────────────────────────────
export default function StudioLayout() {
  const { state, dispatch, refreshOllamaModels } = useApp()
  const [chatKey, setChatKey]           = useState(0)
  const [chatId,  setChatId]            = useState(() => `chat-${Date.now()}`)
  const [activeSession, setActiveSession] = useState(null)   // null = new/current
  const [sessions, setSessions]         = useState(() => readSessions(state.settings))

  const isOnline         = state.backendStatus === 'running'
  const ollamaModels     = Array.isArray(state.ollamaModels) ? state.ollamaModels : []
  const modelInventory   = state.modelInventory
  const modelInventoryLoading = !!state.modelInventoryLoading
  const modelInventoryError   = !!state.modelInventoryError

  const providerStatuses = Object.fromEntries(
    ((modelInventory && Array.isArray(modelInventory.providers)) ? modelInventory.providers : [])
      .map(p => [p.provider, p])
  )

  const getProviderUiState = useCallback((provider) => {
    const meta   = PROVIDER_META[provider]
    const status = providerStatuses[provider] || {}
    const hasSavedKey = !!String(state.settings?.[meta.settingsKey] || '').trim()
    const hasModels   = Array.isArray(status.selectable_models) && status.selectable_models.length > 0
    const hasFetchError = !!String(status.model_fetch_error || '').trim()

    if (!hasSavedKey) return { kind: 'missing', label: '+ key', title: `Add ${meta.label} API key` }
    if (modelInventoryLoading || state.backendStatus === 'starting' || state.backendStatus === 'connecting') {
      return { kind: 'checking', label: 'checking', title: `Checking ${meta.label} models…` }
    }
    if (modelInventoryError || hasFetchError || (!status.ready && !hasModels)) {
      return { kind: 'error', label: 'error', title: hasFetchError ? `${meta.label}: ${status.model_fetch_error}` : `${meta.label} could not be verified` }
    }
    return { kind: 'ok', label: '✓', title: `${meta.label} ready` }
  }, [modelInventoryError, modelInventoryLoading, providerStatuses, state.backendStatus, state.settings])

  const navigate = (view) => dispatch({ type: 'SET_VIEW', view })

  // Refresh session list when chatKey changes (new chat / session loaded)
  useEffect(() => {
    setSessions(readSessions(state.settings))
  }, [chatKey, state.settings])

  // ── Session management ───────────────────────────────────────────────────────
  const handleNewChat = useCallback(() => {
    saveCurrentAsSession(chatId)
    lsSet(CURRENT_HIST_KEY, [])
    const newId = `chat-${Date.now()}`
    setChatId(newId)
    setActiveSession(null)
    setChatKey(k => k + 1)
  }, [chatId])

  const handleLoadSession = useCallback((session) => {
    saveCurrentAsSession(chatId)
    // Remove selected session from history (it becomes current)
    const all = lsGet(SESSIONS_KEY) || []
    lsSet(SESSIONS_KEY, all.filter(s => s.id !== session.id))
    lsSet(CURRENT_HIST_KEY, session.messages)
    setChatId(session.id)
    setActiveSession(session)
    setChatKey(k => k + 1)
  }, [chatId])

  const handleDeleteSession = useCallback((id) => {
    const all = lsGet(SESSIONS_KEY) || []
    lsSet(SESSIONS_KEY, all.filter(s => s.id !== id))
    setSessions(prev => prev.filter(s => s.id !== id))
  }, [])

  return (
    <div className="sl-root">
      {/* ── Left sidebar ── */}
      <div className="sl-sidebar">
        {/* Fixed top section */}
        <div className="sl-sidebar-fixed">
          <button className="sl-new-chat" onClick={handleNewChat}>
            <PlusIcon /> New chat
          </button>

          <div className="sl-conv-label">ACTIVE ASSISTANT</div>
          <button className="sl-conv-item active">
            <ChatDotIcon />
            <span className="sl-conv-current-label">
              {activeSession?.title || 'Current chat'}
            </span>
          </button>

          {sessions.length > 0 && (
            <div className="sl-conv-label sl-conv-label--recent">RECENT SESSIONS</div>
          )}
        </div>

        {/* Scrollable sessions list */}
        <div className="sl-sessions-scroll">
          {sessions.length === 0 ? (
            <div className="sl-sessions-empty">No past chats yet</div>
          ) : (
            sessions.map(s => (
              <div key={s.id} className="sl-session-row">
                <button className="sl-session-btn" onClick={() => handleLoadSession(s)}>
                  <span className="sl-session-title">{s.title}</span>
                  <span className="sl-session-time">{sessionRelTime(s.updatedAt || s.createdAt)}</span>
                </button>
                <button
                  className="sl-session-del"
                  title="Delete"
                  onClick={e => { e.stopPropagation(); handleDeleteSession(s.id) }}
                >×</button>
              </div>
            ))
          )}
        </div>

        {/* Bottom nav */}
        <div className="sl-sidebar-bottom">
          <button className="sl-nav-btn" onClick={() => navigate('home')} title="Home">
            <HomeNavIcon /> Home
          </button>
          <button className="sl-nav-btn" onClick={() => navigate('build')} title="Build">
            <AgentsNavIcon /> Build
          </button>
          <button className="sl-nav-btn" onClick={() => navigate('integrations')} title="Integrations">
            <MCPNavIcon /> Tools
          </button>
          <button className="sl-nav-btn" onClick={() => navigate('runs')} title="Runs">
            <RunsNavIcon /> Runs
          </button>
          <button className="sl-nav-btn" onClick={() => navigate('settings')} title="AI Engines & Settings">
            <SettingsNavIcon /> Settings
          </button>
        </div>
      </div>

      {/* ── Main content ── */}
      <div className="sl-main">
        <div className="sl-topbar">
          <ModelPicker
            ollamaModels={ollamaModels}
            onRefreshOllama={() => refreshOllamaModels(true)}
            providerStatuses={providerStatuses}
            getProviderUiState={getProviderUiState}
          />
          <div className="sl-topbar-spacer" />
          <div className="sl-status">
            <span className={`sl-status-dot ${isOnline ? 'on' : ''}`} />
            <span>{isOnline ? 'connected' : state.backendStatus}</span>
          </div>
        </div>

        <ChatPanel key={chatKey} fullWidth hideHeader studioMode />
      </div>
    </div>
  )
}

// ─── Model Picker (topbar dropdown) ──────────────────────────────────────────
function ModelPicker({ ollamaModels, onRefreshOllama, providerStatuses, getProviderUiState }) {
  const { state, dispatch } = useApp()
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const select = (modelId, disabled) => {
    if (disabled) return
    dispatch({ type: 'SET_MODEL', model: modelId })
    setOpen(false)
  }

  const selected     = state.selectedModel
  const selectedMeta = CLOUD_MODELS.find(m => m.id === selected)
  const displayName  = !selected
    ? 'Auto (backend default)'
    : selectedMeta?.label ?? selected.replace(/^ollama\//, '')
  const selectedProvider = selected ? (selectedMeta?.provider || 'ollama') : null
  const selectedProviderLost = selected && selectedMeta && getProviderUiState(selectedMeta.provider).kind !== 'ok'

  const getModelBadges = (provider, modelId) => {
    const status = providerStatuses[provider] || {}
    const name = String(modelId || '').replace(new RegExp(`^${provider}/`), '')
    return Array.isArray(status.model_badges?.[name]) ? status.model_badges[name] : []
  }

  const isAgentCapable = (provider, modelName) => {
    const status = providerStatuses[provider] || {}
    const details = Array.isArray(status.selectable_model_details) ? status.selectable_model_details : []
    const matched = details.find(item => String(item?.name || '') === String(modelName || ''))
    if (matched && typeof matched.agent_capable === 'boolean') return matched.agent_capable
    if (provider === 'ollama') return false
    if (String(status.model || '') === String(modelName || '') && typeof status.agent_capable === 'boolean') return status.agent_capable
    return false
  }

  useEffect(() => {
    if (!state.selectedModel) return
    if (!resolveAgentCapability(state.selectedModel, { providers: Object.values(providerStatuses) })) {
      dispatch({ type: 'SET_MODEL', model: null })
    }
  }, [dispatch, providerStatuses, state.selectedModel])

  return (
    <div className="mp-root" ref={rootRef}>
      <button className={`mp-trigger ${selectedProviderLost ? 'mp-trigger--warn' : ''}`} onClick={() => setOpen(o => !o)}>
        {selectedProvider && <span className={`mp-provider-dot ${selectedProvider}`} />}
        <span className="mp-trigger-label">{displayName}</span>
        {selectedProviderLost && <span className="mp-trigger-warn" title="API key not configured">⚠</span>}
        <ChevronIcon />
      </button>

      {open && (
        <div className="mp-dropdown">
          {/* Auto */}
          <div className="mp-group">
            <button className={`mp-option ${!selected ? 'active' : ''}`} onClick={() => select(null, false)}>
              <span className="mp-option-name">Auto (backend default)</span>
              {!selected && <span className="mp-option-check">✓</span>}
            </button>
          </div>

          {/* Cloud — grouped per provider */}
          {PROVIDER_ORDER.map(provider => {
            const status     = providerStatuses[provider] || {}
            const ui         = getProviderUiState(provider)
            const isConfigured = ui.kind === 'ok'
            const knownModels  = CLOUD_MODELS.filter(m => m.provider === provider)
            const selectableModels = Array.isArray(status.selectable_models) ? status.selectable_models : []
            const models = selectableModels.length
              ? selectableModels.map(model => {
                  const existing = knownModels.find(item => item.id === `${provider}/${model}`)
                  return existing || { id: `${provider}/${model}`, label: model, provider }
                })
              : knownModels
            const meta = PROVIDER_META[provider]
            return (
              <div key={provider} className="mp-group">
                <div className="mp-group-label">
                  <span className={`mp-provider-dot ${provider}`} />
                  {meta.label}
                  {ui.kind === 'ok'       && <span className="mp-key-badge ok">ready</span>}
                  {ui.kind === 'missing'  && <span className="mp-key-badge missing">no key</span>}
                  {ui.kind === 'checking' && <span className="mp-key-badge checking"><SpinnerIcon className="mp-inline-spinner" />checking</span>}
                  {ui.kind === 'error'    && <span className="mp-key-badge error">error</span>}
                </div>
                {models.map(m => (
                  (() => {
                    const modelName = String(m.id || '').replace(`${provider}/`, '')
                    const agentCapable = isAgentCapable(provider, modelName)
                    const disabled = !isConfigured || !agentCapable
                    return (
                  <button
                    key={m.id}
                    className={`mp-option ${selected === m.id ? 'active' : ''} ${disabled ? 'mp-option--dim' : ''}`}
                    onClick={() => select(m.id, disabled)}
                    title={!isConfigured ? ui.title : !agentCapable ? 'No agent capability: tool/function calls unavailable.' : m.label}
                    disabled={disabled}
                  >
                    <span className="mp-option-name">{m.label}</span>
                    {getModelBadges(provider, m.id).map(badge => (
                      <span key={`${m.id}:${badge}`} className={`mp-model-badge ${badge}`}>{badge}</span>
                    ))}
                    <span className={`mp-model-badge ${agentCapable ? 'agent' : 'noagent'}`}>{agentCapable ? 'agent' : 'no-agent'}</span>
                    {disabled && <span className="mp-lock">🔒</span>}
                    {selected === m.id && !disabled && <span className="mp-option-check">✓</span>}
                  </button>
                    )
                  })()
                ))}
                {!isConfigured && (
                  <button
                    className="mp-add-key-btn"
                    onClick={() => { dispatch({ type: 'SET_VIEW', view: 'settings' }); setOpen(false) }}
                  >
                    {ui.kind === 'missing' ? `+ Add ${meta.label} key →` : ui.kind === 'checking' ? `Checking ${meta.label}…` : `Resolve ${meta.label} error →`}
                  </button>
                )}
              </div>
            )
          })}

          {/* Local Ollama */}
          <div className="mp-group">
            <div className="mp-group-label mp-group-label--row">
              <span className="mp-provider-dot ollama" />
              Local (Ollama)
              <button className="mp-refresh-btn" onClick={onRefreshOllama} title="Refresh Ollama models">
                <RefreshIcon />
              </button>
            </div>
            {ollamaModels.length === 0 ? (
              <div className="mp-empty">
                No local models found.
                <button className="mp-add-key-btn" onClick={() => { dispatch({ type: 'SET_VIEW', view: 'models' }); setOpen(false) }}>
                  Pull a model →
                </button>
              </div>
            ) : (
              ollamaModels.map(m => {
                const id = `ollama/${m.name || m}`
                const disabled = true
                return (
                  <button
                    key={id}
                    className={`mp-option ${selected === id ? 'active' : ''} mp-option--dim`}
                    onClick={() => select(id, disabled)}
                    title="Local models disabled for agent mode: no supported agent capability."
                    disabled={disabled}
                  >
                    <span className="mp-option-name">{m.name || m}</span>
                    <span className="mp-model-badge noagent">no-agent</span>
                    {m.size && <span className="mp-option-size">{(m.size / 1e9).toFixed(1)} GB</span>}
                    <span className="mp-lock">🔒</span>
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SpinnerIcon({ className = '' }) {
  return (
    <svg className={className} width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <path d="M21 12a9 9 0 1 1-3.2-6.9" />
    </svg>
  )
}

function RefreshIcon({ spinning = false }) {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
      style={spinning ? { animation: 'sl-spin .7s linear infinite' } : {}}>
      <polyline points="23 4 23 10 17 10"/>
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
    </svg>
  )
}

// ─── Icons ────────────────────────────────────────────────────────────────────
function PlusIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
}
function ChatDotIcon() {
  return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
}
function HomeNavIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>
}
function RunsNavIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
}
function AgentsNavIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8m-4-4v4"/><circle cx="8" cy="10" r="1.5" fill="currentColor"/><circle cx="12" cy="10" r="1.5" fill="currentColor"/><circle cx="16" cy="10" r="1.5" fill="currentColor"/></svg>
}
function MCPNavIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12"/></svg>
}
function ModelsNavIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
}
function SettingsNavIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
}
function ChevronIcon() {
  return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="6 9 12 15 18 9"/></svg>
}
