import React, { useState, useRef, useEffect, useCallback, useMemo, useReducer } from 'react'
import { useApp } from '../contexts/AppContext'
import { basename, resolveAgentCapability, resolveContextWindow, resolveSelectedModel } from '../lib/modelSelection'

// ─── Chat history persistence ────────────────────────────────────────────────
const CHAT_HISTORY_KEY = 'kendr_chat_history_v1'
const SESSIONS_KEY     = 'kendr_sessions_v1'
const MAX_STORED_MESSAGES = 200
const MAX_SESSIONS = 100

function loadHistory() {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY)
    if (!raw) return []
    const msgs = JSON.parse(raw)
    return Array.isArray(msgs) ? msgs.map(m => ({ ...m, ts: new Date(m.ts) })) : []
  } catch { return [] }
}

function saveHistory(messages) {
  try {
    const toSave = messages
      .filter(m => (
        m.role === 'user'
        || (m.role === 'assistant' && ['thinking', 'streaming', 'awaiting', 'done', 'error'].includes(String(m.status || '')))
      ))
      .slice(-MAX_STORED_MESSAGES)
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(toSave))
  } catch (_) {}
}

function loadSessions() {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
    if (!raw) return []
    return JSON.parse(raw) || []
  } catch { return [] }
}

function saveSessions(sessions) {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(-MAX_SESSIONS)))
  } catch {}
}

function pruneOldSessions(sessions, retentionDays) {
  if (!retentionDays || retentionDays <= 0) return sessions
  const cutoff = Date.now() - retentionDays * 24 * 60 * 60 * 1000
  return sessions.filter(s => new Date(s.updatedAt || s.createdAt).getTime() >= cutoff)
}

function makeSessionTitle(messages) {
  const first = messages.find(m => m.role === 'user')
  return String(first?.content || '').slice(0, 60) || 'New conversation'
}

function formatRelTime(dateStr) {
  const d = new Date(dateStr)
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60000) return 'just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// ─── Chat-local state ────────────────────────────────────────────────────────
const initChat = {
  messages: [],          // [{id,role,content,steps,status,runId,artifacts,progress,ts}]
  streaming: false,
  activeRunId: null,
  mode: 'chat',          // chat | agent | research | security
  awaitingContext: null, // {runId,workflowId,prompt,kind}
}

function chatReducer(s, a) {
  switch (a.type) {
    case 'ADD_MSG':     return { ...s, messages: [...s.messages, a.msg] }
    case 'UPD_MSG':     return { ...s, messages: s.messages.map(m => m.id === a.id ? { ...m, ...a.patch } : m) }
    case 'APPEND_MSG_CONTENT':
      return {
        ...s,
        messages: s.messages.map(m => (
          m.id === a.id ? { ...m, content: `${m.content || ''}${a.delta || ''}` } : m
        )),
      }
    case 'ADD_STEP': {
      const msgs = s.messages.map(m => {
        if (m.id !== a.msgId) return m
        const steps = [...(m.steps || [])]
        const idx = steps.findIndex(st => st.stepId === a.step.stepId)
        if (idx >= 0) { steps[idx] = { ...steps[idx], ...a.step } }
        else steps.push(a.step)
        return { ...m, steps }
      })
      return { ...s, messages: msgs }
    }
    case 'ADD_PROGRESS': {
      const msgs = s.messages.map(m => {
        if (m.id !== a.msgId) return m
        const item = {
          id: String(a.item?.id || `p-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
          ts: a.item?.ts || new Date().toISOString(),
          title: String(a.item?.title || '').trim(),
          detail: String(a.item?.detail || '').trim(),
          kind: String(a.item?.kind || '').trim(),
          status: String(a.item?.status || '').trim(),
          command: String(a.item?.command || '').trim(),
          cwd: String(a.item?.cwd || '').trim(),
          actor: String(a.item?.actor || '').trim(),
          durationLabel: String(a.item?.durationLabel || '').trim(),
          exitCode: a.item?.exitCode,
        }
        if (!item.title && !item.detail) return m
        const prev = Array.isArray(m.progress) ? m.progress : []
        const last = prev[0]
        if (last && last.title === item.title && last.detail === item.detail) return m
        const next = [item, ...prev].slice(0, 14)
        return { ...m, progress: next }
      })
      return { ...s, messages: msgs }
    }
    case 'SET_STREAMING':  return { ...s, streaming: a.val }
    case 'SET_RUN':        return { ...s, activeRunId: a.id }
    case 'SET_MODE':       return { ...s, mode: a.mode }
    case 'SET_AWAITING':   return { ...s, awaitingContext: a.ctx }
    case 'CLEAR_AWAITING': return { ...s, awaitingContext: null }
    case 'CLEAR':          return { ...initChat, mode: s.mode }
    case 'LOAD_MSGS':      return { ...initChat, mode: s.mode, messages: a.messages }
    default: return s
  }
}

// ─── Build POST payload ───────────────────────────────────────────────────────
function buildPayload(text, chatId, runId, projectRoot, mode, dr, attachments = [], studioMode = false, useMcp = false) {
  const localPaths = Array.isArray(attachments) ? attachments.map(item => item.path).filter(Boolean) : []
  const normalizedText = mode === 'agent'
    ? `Handle this in agent mode. Do the detailed work, think step by step, use attached local files/folders if relevant, and return a concise final answer.\n\nUser request: ${text}`
    : text
  const base = {
    text: normalizedText,
    channel:           'webchat',
    sender_id:         'desktop_user',
    chat_id:           chatId,
    run_id:            runId,
    working_directory: studioMode ? undefined : (projectRoot || undefined),
    use_mcp:           useMcp,
  }
  if (mode === 'agent') {
    return {
      ...base,
      local_drive_paths: localPaths.length ? localPaths : undefined,
      local_drive_recursive: localPaths.length ? true : undefined,
    }
  }
  if (mode !== 'research') {
    return {
      ...base,
      local_drive_paths: localPaths.length ? localPaths : undefined,
      local_drive_recursive: localPaths.length ? true : undefined,
    }
  }

  // Parse explicit links from textarea
  const links = (dr.links || '').split(/[\n,\s]+/)
    .map(s => s.trim()).filter(s => /^https?:\/\//i.test(s))
  const webLinks = dr.webSearchEnabled ? links : []

  // Compute research_sources: checked remote + 'local' if paths present
  const remoteSources = dr.webSearchEnabled ? dr.sources : []
  const mergedLocalPaths = Array.from(new Set([...(dr.localPaths || []), ...localPaths]))
  const allSources = mergedLocalPaths.length
    ? Array.from(new Set([...remoteSources, 'local']))
    : remoteSources

  const payload = {
    ...base,
    deep_research_mode:              true,
    long_document_mode:              true,
    workflow_type:                   'deep_research',
    long_document_pages:             dr.pages,
    research_output_formats:         dr.outputFormats,
    research_citation_style:         dr.citationStyle,
    research_enable_plagiarism_check: dr.plagiarismCheck,
    research_web_search_enabled:     dr.webSearchEnabled,
    research_date_range:             dr.dateRange,
    research_sources:                allSources,
    research_max_sources:            dr.maxSources || 0,
    research_checkpoint_enabled:     dr.checkpointing,
    deep_research_source_urls:       webLinks,
  }
  if (mergedLocalPaths.length) {
    payload.local_drive_paths              = mergedLocalPaths
    payload.local_drive_recursive          = true
    payload.local_drive_force_long_document = true
  }
  return payload
}

function modeLabel(mode) {
  if (mode === 'agent') return 'Agent'
  if (mode === 'research') return 'Deep Research'
  return 'Chat'
}

function normalizeChecklistStatus(value) {
  const status = String(value || '').trim().toLowerCase()
  if (['completed', 'done', 'success', 'ok'].includes(status)) return 'completed'
  if (['running', 'in_progress', 'started', 'active'].includes(status)) return 'running'
  if (['awaiting_approval', 'awaiting_input', 'awaiting'].includes(status)) return 'awaiting'
  if (['failed', 'error'].includes(status)) return 'failed'
  if (['blocked'].includes(status)) return 'blocked'
  if (['skipped'].includes(status)) return 'skipped'
  return status || 'pending'
}

function sanitizeStatusMessage(message) {
  const raw = String(message || '').trim()
  const normalized = raw.toLowerCase()
  if (!raw) return ''
  if (normalized === 'resuming run...') return 'Continuing approved plan...'
  if (normalized === 'restoring context from the paused run...') return 'Loading paused checklist...'
  if (normalized === 'executing queued tasks...') return 'Running remaining checklist steps...'
  if (normalized === 'collecting outputs and preparing the final response...') return 'Wrapping up final answer...'
  return raw
}

function extractChecklist(result) {
  if (!result || typeof result !== 'object') return []
  const shellSteps = Array.isArray(result.shell_plan_steps) ? result.shell_plan_steps : []
  if (shellSteps.length) {
    return shellSteps.map((step, index) => ({
      step: Number(step.step || (index + 1)),
      title: String(step.title || step.description || `Step ${index + 1}`).trim() || `Step ${index + 1}`,
      status: normalizeChecklistStatus(step.status || (step.done ? 'completed' : 'pending')),
      detail: String(step.detail || step.reason || '').trim(),
      command: String(step.command || '').trim(),
      stdout: String(step.stdout || '').trim(),
      stderr: String(step.stderr || '').trim(),
      reason: String(step.reason || '').trim(),
      optional: !!step.optional,
      done: !!step.done || ['completed', 'skipped'].includes(normalizeChecklistStatus(step.status)),
      returnCode: step.return_code,
    }))
  }

  const planSteps = Array.isArray(result.plan_steps) ? result.plan_steps : []
  if (planSteps.length) {
    const activeIndex = Math.max(0, Number(result.plan_step_index || 0))
    return planSteps.map((step, index) => {
      const rawStatus = normalizeChecklistStatus(step.status || '')
      const status = rawStatus || (index < activeIndex ? 'completed' : index === activeIndex ? 'running' : 'pending')
      return {
        step: index + 1,
        title: String(step.title || step.name || step.description || `Step ${index + 1}`).trim() || `Step ${index + 1}`,
        status,
        detail: String(step.success_criteria || step.description || '').trim(),
        command: '',
        stdout: '',
        stderr: '',
        reason: String(step.reason || '').trim(),
        optional: false,
        done: ['completed', 'skipped'].includes(status),
        returnCode: null,
      }
    })
  }

  return []
}

function latestChecklistMessage(messages) {
  const safe = Array.isArray(messages) ? messages : []
  for (let i = safe.length - 1; i >= 0; i -= 1) {
    const msg = safe[i]
    if (msg?.role === 'assistant' && Array.isArray(msg?.checklist) && msg.checklist.length) return msg
  }
  return null
}

function buildSimpleHistory(messages, maxTurns = 12) {
  const safe = Array.isArray(messages) ? messages : []
  return safe
    .filter(m => (
      (m?.role === 'user' || m?.role === 'assistant')
      && String(m?.content || '').trim()
      && !['thinking', 'streaming'].includes(String(m?.status || ''))
    ))
    .slice(-maxTurns)
    .map(m => ({
      role: m.role,
      content: String(m.content || '').trim(),
    }))
}

function estimateObjectTokens(value) {
  try {
    const raw = JSON.stringify(value)
    return Math.max(0, Math.round(String(raw || '').length / 4))
  } catch {
    return 0
  }
}

function formatDuration(totalSeconds) {
  const s = Math.max(0, Number(totalSeconds) || 0)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m ${sec}s`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

function isShellProgressItem(item) {
  if (!item || typeof item !== 'object') return false
  const kind = String(item.kind || '').toLowerCase()
  const title = String(item.title || '').toLowerCase()
  const detail = String(item.detail || '').toLowerCase()
  const command = String(item.command || '').trim()
  if (command) return true
  if (kind.includes('command') || kind.includes('shell')) return true
  return /\bshell command\b|\brunning command\b|\bos[_\s-]?agent\b/.test(`${title} ${detail}`)
}

function shellCardFromProgress(progress = []) {
  const items = (Array.isArray(progress) ? progress : []).filter(isShellProgressItem)
  if (!items.length) return null
  const running = items.find((it) => ['running', 'started', 'in_progress'].includes(String(it.status || '').toLowerCase()))
  const primary = running || items[0]
  if (!primary) return null

  const primaryStatus = String(primary.status || '').toLowerCase()
  const command = String(primary.command || '').trim()
  let output = ''
  if (['completed', 'failed', 'error'].includes(primaryStatus)) {
    output = String(primary.detail || '').trim()
  } else if (command) {
    const companion = items.find((it) => (
      it !== primary
      && String(it.command || '').trim() === command
      && ['completed', 'failed', 'error'].includes(String(it.status || '').toLowerCase())
      && String(it.detail || '').trim()
    ))
    if (companion) output = String(companion.detail || '').trim()
  }

  return {
    title: String(primary.title || 'Shell command').trim() || 'Shell command',
    command,
    output,
    status: primaryStatus || 'running',
    cwd: String(primary.cwd || '').trim(),
    durationLabel: String(primary.durationLabel || '').trim(),
    exitCode: primary.exitCode,
  }
}

function inferExecutionBlockers({ msg, shellCard, progress = [], checklist = [] }) {
  const textParts = []
  const addText = (value) => {
    const raw = String(value || '').trim()
    if (raw) textParts.push(raw)
  }

  addText(msg?.content)
  addText(shellCard?.output)
  for (const item of Array.isArray(progress) ? progress : []) {
    addText(item?.title)
    addText(item?.detail)
  }
  for (const item of Array.isArray(checklist) ? checklist : []) {
    addText(item?.title)
    addText(item?.detail)
    addText(item?.reason)
    addText(item?.stdout)
    addText(item?.stderr)
  }

  const observedMatch = String(msg?.content || '').match(/Observed blockers:\s*([\s\S]*?)(?:\n\s*\n|$)/i)
  if (observedMatch?.[1]) {
    for (const line of observedMatch[1].split('\n')) {
      const cleaned = line.replace(/^\s*-\s*/, '').trim()
      if (cleaned) textParts.push(cleaned)
    }
  }

  const corpus = textParts.join('\n').toLowerCase()
  if (!corpus.trim()) return []

  const chips = []
  const pushChip = (key, label, tone = 'warn') => {
    if (chips.some((item) => item.key === key)) return
    chips.push({ key, label, tone })
  }

  if (
    /dockerdesktoplinuxengine|docker engine\/desktop was not actually running|docker engine not responding|cannot connect to the docker daemon|docker daemon|the system cannot find the file specified.*docker/i.test(corpus)
  ) {
    pushChip('engine-down', 'Engine Down', 'err')
  }
  if (
    /wrong shell|not a valid statement separator|\/dev\/null|command -v|planner emitted syntax for the wrong shell|powershell plan uses|is not recognized as the name of a cmdlet|unexpected token '\|\|'/i.test(corpus)
  ) {
    pushChip('wrong-shell', 'Wrong Shell', 'err')
  }
  if (
    /required app\/tool was missing|not discoverable from this machine|cannot find the file specified|was not found|could not find|not recognized as the name of a cmdlet|no such file or directory|missing or not discoverable/i.test(corpus)
  ) {
    pushChip('app-missing', 'App Missing', 'warn')
  }
  if (
    /outside the allowed execution scope|outside the allowed scope|blocked by execution policy|policy block|approval_required|requires your approval/i.test(corpus)
  ) {
    pushChip('policy-block', 'Policy Block', 'warn')
  }
  if (
    /permission denied|access is denied|administrator|elevation required|sudo|operation not permitted/i.test(corpus)
  ) {
    pushChip('permission', 'Need Permission', 'warn')
  }
  if (
    /timed out|timeout|could not resolve|temporary failure in name resolution|connection refused|network is unreachable|failed to fetch/i.test(corpus)
  ) {
    pushChip('network', 'Network Issue', 'warn')
  }

  const blockedSteps = (Array.isArray(checklist) ? checklist : []).filter((item) => {
    const status = normalizeChecklistStatus(item?.status)
    return status === 'blocked' || status === 'failed'
  }).length
  if (!chips.length && blockedSteps > 0) {
    pushChip('blocked', blockedSteps > 1 ? 'Steps Blocked' : 'Step Blocked', 'warn')
  }

  return chips.slice(0, 4)
}

function readBlobAsDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error || new Error('read_failed'))
    reader.readAsDataURL(blob)
  })
}

function detectAttachmentType(filePath, fallback = 'file') {
  const raw = String(filePath || '').trim().toLowerCase()
  if (!raw) return fallback
  if (/\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(raw)) return 'image'
  return fallback
}

function attachmentPreviewSrc(item) {
  if (!item || item.type !== 'image') return ''
  const preview = String(item.previewUrl || '').trim()
  if (preview) return preview
  const rawPath = String(item.path || '').trim()
  if (!rawPath) return ''
  const normalized = rawPath.replace(/\\/g, '/')
  if (/^[a-z]:\//i.test(normalized)) return `file:///${normalized}`
  if (normalized.startsWith('/')) return `file://${normalized}`
  return rawPath
}

// ─── Deep Research default settings ─────────────────────────────────────────
const DR_DEFAULTS = {
  pages: 25,
  citationStyle: 'apa',
  dateRange: 'all_time',
  maxSources: 0,
  outputFormats: ['pdf', 'docx', 'html', 'md'],
  webSearchEnabled: true,
  sources: ['web'],
  plagiarismCheck: true,
  checkpointing: false,
  localPaths: [],   // native FS paths (Electron folder picker)
  links: '',        // newline-separated URLs
  collapsed: false,
}

// ─── Component ───────────────────────────────────────────────────────────────
export default function ChatPanel({ fullWidth = false, hideHeader = false, studioMode = false }) {
  const { state: appState, dispatch: appDispatch, refreshModelInventory } = useApp()
  const api = window.kendrAPI
  const [chat, dispatch] = useReducer(chatReducer, undefined, () => ({ ...initChat, messages: loadHistory() }))
  const [input, setInput] = useState('')
  const [resumeInput, setResumeInput] = useState('')
  const [chatId, setChatId] = useState(() => `chat-${Date.now()}`)
  const [dr, setDr] = useState(DR_DEFAULTS)
  const [attachments, setAttachments] = useState([])
  const [mcpEnabled, setMcpEnabled] = useState(false)
  const [mcpServerCount, setMcpServerCount] = useState(0)
  const [mcpUndiscovered, setMcpUndiscovered] = useState(0)
  const [machineStatus, setMachineStatus] = useState(null)
  const [machineStatusLoaded, setMachineStatusLoaded] = useState(false)
  const [machineSyncRunning, setMachineSyncRunning] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [sessions, setSessions] = useState(() => loadSessions())
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const esRef = useRef(null)
  const resumeAttemptedRunRef = useRef('')
  const apiBase = appState.backendUrl || 'http://127.0.0.1:2151'
  const updateDr = (patch) => setDr(s => ({ ...s, ...patch }))
  const selectedModelMeta = resolveSelectedModel(appState.selectedModel)
  const isSimpleStudioChat = studioMode && chat.mode === 'chat'
  const modelInventory = appState.modelInventory
  const selectedModelAgentCapable = resolveAgentCapability(appState.selectedModel, modelInventory)
  const contextLimit = resolveContextWindow(appState.selectedModel, modelInventory)
  const payloadPreview = useMemo(() => {
    const draftText = String(input || '').trim()
    const body = buildPayload(
      draftText,
      chatId,
      'ctx-preview',
      appState.projectRoot,
      chat.mode,
      dr,
      attachments,
      studioMode,
      mcpEnabled,
    )
    body.history = buildSimpleHistory(chat.messages, 14)
    if (appState.selectedModel) {
      const selected = resolveSelectedModel(appState.selectedModel)
      if (selected.provider) body.provider = selected.provider
      if (selected.model) body.model = selected.model
    }
    body.context_limit = contextLimit
    if (isSimpleStudioChat) body.stream = true
    return body
  }, [input, chatId, appState.projectRoot, chat.mode, dr, attachments, studioMode, mcpEnabled, chat.messages, appState.selectedModel, isSimpleStudioChat, contextLimit])
  const estimatedContextTokens = estimateObjectTokens(payloadPreview)
  const contextPct = Math.min(100, Math.round((estimatedContextTokens / Math.max(contextLimit, 1)) * 100))
  const stickyChecklistMsg = useMemo(() => latestChecklistMessage(chat.messages), [chat.messages])
  const stickyChecklist = Array.isArray(stickyChecklistMsg?.checklist) ? stickyChecklistMsg.checklist : []

  // Close the SSE stream when the panel unmounts (e.g. explicit new-chat remount)
  useEffect(() => {
    return () => { esRef.current?.close() }
  }, [])

  useEffect(() => {
    if (!appState.activeRunId) resumeAttemptedRunRef.current = ''
  }, [appState.activeRunId])

  useEffect(() => {
    if (chat.mode === 'agent' && !selectedModelAgentCapable) {
      dispatch({ type: 'SET_MODE', mode: 'chat' })
    }
  }, [chat.mode, selectedModelAgentCapable])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat.messages])

  // Persist chat history continuously so an active run survives panel remounts.
  useEffect(() => {
    saveHistory(chat.messages)
  }, [chat.messages])

  useEffect(() => {
    refreshModelInventory(false)
  }, [refreshModelInventory])

  // Prune sessions whenever retention setting changes
  useEffect(() => {
    const days = appState.settings?.chatHistoryRetentionDays ?? 14
    setSessions(prev => {
      const pruned = pruneOldSessions(prev, days)
      if (pruned.length !== prev.length) saveSessions(pruned)
      return pruned
    })
  }, [appState.settings?.chatHistoryRetentionDays])

  // ── Session helpers ──────────────────────────────────────────────────────────
  const saveCurrentSession = useCallback(() => {
    if (chat.messages.length === 0) return
    const session = {
      id: chatId,
      title: makeSessionTitle(chat.messages),
      createdAt: String(chat.messages[0]?.ts || new Date().toISOString()),
      updatedAt: new Date().toISOString(),
      messages: chat.messages,
    }
    const days = appState.settings?.chatHistoryRetentionDays ?? 14
    setSessions(prev => {
      const updated = pruneOldSessions([...prev.filter(s => s.id !== chatId), session], days)
      saveSessions(updated)
      return updated
    })
  }, [chat.messages, chatId, appState.settings?.chatHistoryRetentionDays])

  const newChat = useCallback(() => {
    saveCurrentSession()
    dispatch({ type: 'CLEAR' })
    saveHistory([])
    setShowHistory(false)
    setAttachments([])
    setResumeInput('')
    setChatId(`chat-${Date.now()}`)
  }, [saveCurrentSession])

  const compactContext = useCallback(async () => {
    if (!chat.messages.length || chat.streaming) return
    saveCurrentSession()
    try {
      const resp = await fetch(`${apiBase}/api/chat/compact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel: 'webchat',
          sender_id: 'desktop_user',
          chat_id: chatId,
          history: buildSimpleHistory(chat.messages, 200),
          context_limit: contextLimit,
        }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || data.error) throw new Error(data.error || data.detail || resp.statusText)
      const note = {
        id: `c-${Date.now()}`,
        role: 'assistant',
        content: `Context compacted into ${data.summary_file || 'summary.md'} (${Number(data.summary_tokens || 0).toLocaleString()} tokens, level ${data.compaction_level || 0}).`,
        status: 'done',
        mode: 'chat',
        modeLabel: 'Compacted',
        ts: new Date(),
      }
      dispatch({ type: 'ADD_MSG', msg: note })
      saveHistory([...chat.messages, note])
      setShowHistory(false)
    } catch (err) {
      const note = {
        id: `c-${Date.now()}`,
        role: 'assistant',
        content: `Context compaction failed: ${err.message}`,
        status: 'error',
        mode: 'chat',
        modeLabel: 'Compacted',
        ts: new Date(),
      }
      dispatch({ type: 'ADD_MSG', msg: note })
      saveHistory([...chat.messages, note])
    }
  }, [apiBase, chat.messages, chat.streaming, chatId, contextLimit, saveCurrentSession])

  const loadSession = useCallback((session) => {
    esRef.current?.close()
    saveCurrentSession()
    const msgs = session.messages.map(m => ({ ...m, ts: new Date(m.ts) }))
    dispatch({ type: 'LOAD_MSGS', messages: msgs })
    dispatch({ type: 'SET_STREAMING', val: false })
    appDispatch({ type: 'SET_STREAMING', streaming: false })
    saveHistory(msgs)
    setShowHistory(false)
  }, [saveCurrentSession, appDispatch])

  const deleteSession = useCallback((id) => {
    setSessions(prev => {
      const updated = prev.filter(s => s.id !== id)
      saveSessions(updated)
      return updated
    })
  }, [])

  // Auto-enable MCP when switching to agent mode; keep state when switching away
  useEffect(() => {
    if (chat.mode === 'agent') setMcpEnabled(true)
  }, [chat.mode])

  // Fetch enabled MCP server count and check for undiscovered servers
  useEffect(() => {
    fetch(`${apiBase}/api/mcp/servers`)
      .then(r => r.ok ? r.json() : [])
      .then(data => {
        const servers = Array.isArray(data) ? data : (data.servers || [])
        const enabled = servers.filter(s => s.enabled !== false)
        setMcpServerCount(enabled.length)
        setMcpUndiscovered(enabled.filter(s => !s.tool_count || s.tool_count === 0).length)
      })
      .catch(() => {})
  }, [apiBase, mcpEnabled])

  const syncWorkingDirectory = (appState.projectRoot || appState.settings?.projectRoot || '').trim()

  const fetchMachineStatus = useCallback(async () => {
    if (!apiBase) return null
    try {
      const q = syncWorkingDirectory ? `?working_directory=${encodeURIComponent(syncWorkingDirectory)}` : ''
      const resp = await fetch(`${apiBase}/api/machine/status${q}`)
      if (!resp.ok) {
        setMachineStatusLoaded(true)
        return null
      }
      const data = await resp.json().catch(() => ({}))
      const status = data?.status && typeof data.status === 'object' ? data.status : null
      if (status) setMachineStatus(status)
      setMachineStatusLoaded(true)
      return status
    } catch (_) {
      setMachineStatusLoaded(true)
      return null
    }
  }, [apiBase, syncWorkingDirectory])

  const triggerMachineSync = useCallback(async (scope = 'machine', isAuto = false) => {
    if (machineSyncRunning) return
    setMachineSyncRunning(true)
    try {
      const resp = await fetch(`${apiBase}/api/machine/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope,
          working_directory: syncWorkingDirectory || undefined,
        }),
      })
      const data = await resp.json().catch(() => ({}))
      if (resp.ok && data?.status && typeof data.status === 'object') {
        setMachineStatus(data.status)
        if (api?.settings?.set) {
          const nowIso = new Date().toISOString()
          await api.settings.set('machineLastAutoSyncAt', nowIso)
          appDispatch({ type: 'SET_SETTINGS', settings: { machineLastAutoSyncAt: nowIso } })
        }
      }
    } catch (_) {
    } finally {
      setMachineSyncRunning(false)
      if (!isAuto) fetchMachineStatus()
    }
  }, [apiBase, syncWorkingDirectory, machineSyncRunning, api, appDispatch, fetchMachineStatus])

  useEffect(() => {
    fetchMachineStatus()
  }, [fetchMachineStatus])

  useEffect(() => {
    const id = setInterval(() => { fetchMachineStatus() }, 60 * 1000)
    return () => clearInterval(id)
  }, [fetchMachineStatus])

  useEffect(() => {
    const enabled = !!appState.settings?.machineAutoSyncEnabled
    if (!enabled) return
    if (machineSyncRunning) return
    const intervalDays = Math.max(1, Math.min(30, Number(appState.settings?.machineAutoSyncIntervalDays || 7)))
    const lastRaw = String(appState.settings?.machineLastAutoSyncAt || '').trim()
    const lastTs = lastRaw ? Date.parse(lastRaw) : 0
    const dueMs = intervalDays * 24 * 60 * 60 * 1000
    const now = Date.now()
    if (!lastTs || Number.isNaN(lastTs) || now - lastTs >= dueMs) {
      triggerMachineSync('machine', true)
    }
  }, [appState.settings, machineSyncRunning, triggerMachineSync])

  // ── Send message ────────────────────────────────────────────────────────────
  const send = useCallback(async (text, isResume = false) => {
    const msg = (typeof text === 'string' ? text.trim() : '') || input.trim()
    if (!msg || chat.streaming) return
    setInput('')
    setResumeInput('')

    const runId = `ui-${Date.now().toString(36)}`
    const userMsgId = `u-${runId}`
    const resumeMessageId = String(chat.awaitingContext?.messageId || '').trim()
    const asstMsgId = isResume && resumeMessageId ? resumeMessageId : `a-${runId}`

    const currentMode = chat.mode
    const currentModeLabel = modeLabel(currentMode)
    const sentAttachments = Array.isArray(attachments) ? attachments.map((item) => ({ ...item })) : []

    dispatch({
      type: 'ADD_MSG',
      msg: {
        id: userMsgId,
        role: 'user',
        content: msg,
        attachments: sentAttachments,
        mode: currentMode,
        modeLabel: currentModeLabel,
        ts: new Date(),
      },
    })
    dispatch({ type: 'SET_STREAMING', val: true })
    dispatch({ type: 'SET_RUN', id: runId })
    dispatch({ type: 'CLEAR_AWAITING' })
    setAttachments([])

    if (isResume && resumeMessageId) {
      dispatch({
        type: 'UPD_MSG',
        id: asstMsgId,
        patch: {
          content: '',
          status: 'thinking',
          runId: isSimpleStudioChat ? null : runId,
          runStartedAt: new Date().toISOString(),
          mode: currentMode,
          modeLabel: currentModeLabel,
          statusText: 'Continuing approved plan...',
        },
      })
    } else {
      dispatch({
        type: 'ADD_MSG',
        msg: {
          id: asstMsgId,
          role: 'assistant',
          content: '',
          steps: [],
          progress: [],
          checklist: [],
          status: 'thinking',
          runId: isSimpleStudioChat ? null : runId,
          runStartedAt: new Date().toISOString(),
          mode: currentMode,
          modeLabel: currentModeLabel,
          ts: new Date(),
        }
      })
    }

    appDispatch({ type: 'SET_STREAMING', streaming: true })

    try {
      const endpoint = isResume && chat.awaitingContext
        ? `${apiBase}/api/chat/resume`
        : isSimpleStudioChat
          ? `${apiBase}/api/chat/simple`
          : `${apiBase}/api/chat`

      const body = isResume && chat.awaitingContext
        ? {
            run_id:      chat.awaitingContext.runId,
            workflow_id: chat.awaitingContext.workflowId,
            text:        msg,
            channel:     'webchat',
          }
        : buildPayload(msg, chatId, runId, appState.projectRoot, chat.mode, dr, sentAttachments, studioMode, mcpEnabled)
      if (!isResume && appState.selectedModel) {
        const selected = resolveSelectedModel(appState.selectedModel)
        if (selected.provider) body.provider = selected.provider
        if (selected.model) body.model = selected.model
      }
      if (!isResume) {
        body.history = buildSimpleHistory(chat.messages, 14)
        body.context_limit = contextLimit
      }

      if (isSimpleStudioChat && !isResume) {
        body.stream = true
        const resp = await fetch(endpoint, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify(body),
        })
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok) {
          refreshModelInventory(true)
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { content: data.error || data.detail || resp.statusText, status: 'error', runId: null } })
          dispatch({ type: 'SET_STREAMING', val: false })
          appDispatch({ type: 'SET_STREAMING', streaming: false })
          return
        }

        if (data.streaming) {
          const effectiveRunId = data.run_id || runId
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { runId: effectiveRunId, status: 'thinking' } })
          dispatch({ type: 'SET_RUN', id: effectiveRunId })
          appDispatch({ type: 'SET_ACTIVE_RUN', runId: effectiveRunId })
          openStream(effectiveRunId, asstMsgId)
          return
        } else {
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { content: data.answer || '', status: 'done', runId: null, artifacts: [] } })
          dispatch({ type: 'SET_STREAMING', val: false })
          appDispatch({ type: 'SET_STREAMING', streaming: false })
          return
        }
      }

      const resp = await fetch(endpoint, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      })

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        refreshModelInventory(true)
        dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { content: err.error || err.detail || resp.statusText, status: 'error' } })
        dispatch({ type: 'SET_STREAMING', val: false })
        appDispatch({ type: 'SET_STREAMING', streaming: false })
        return
      }

      const { run_id: srvRunId } = await resp.json().catch(() => ({}))
      const effectiveRunId = srvRunId || runId

      dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { runId: effectiveRunId, status: 'thinking' } })
      dispatch({ type: 'SET_RUN', id: effectiveRunId })
      appDispatch({ type: 'SET_ACTIVE_RUN', runId: effectiveRunId })

      openStream(effectiveRunId, asstMsgId)
    } catch (err) {
      refreshModelInventory(true)
      dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { content: `Cannot reach backend: ${err.message}`, status: 'error' } })
      dispatch({ type: 'SET_STREAMING', val: false })
      appDispatch({ type: 'SET_STREAMING', streaming: false })
    }
  }, [input, chat.streaming, chat.awaitingContext, chat.mode, apiBase, appState.projectRoot, appState.selectedModel, chatId, dr, attachments, studioMode, isSimpleStudioChat, mcpEnabled, appDispatch, refreshModelInventory, contextLimit])

  // ── SSE stream ──────────────────────────────────────────────────────────────
  const openStream = useCallback((runId, asstMsgId) => {
    esRef.current?.close()
    const es = new EventSource(`${apiBase}/api/stream?run_id=${encodeURIComponent(runId)}`)
    esRef.current = es

    let stepCounter = 0
    let closed = false
    const closeClean = () => { closed = true; es.close() }

    es.addEventListener('status', e => {
      try {
        const d = JSON.parse(e.data)
        if (d.status && d.status !== 'connected') {
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { statusText: sanitizeStatusMessage(d.message || d.status) } })
          dispatch({
            type: 'ADD_PROGRESS',
            msgId: asstMsgId,
            item: {
              id: `status-${Date.now()}`,
              title: 'Runtime update',
              detail: sanitizeStatusMessage(d.message || d.status || ''),
              kind: 'status',
              status: d.status || 'running',
            },
          })
        }
      } catch (_) {}
    })

    es.addEventListener('step', e => {
      try {
        const step = JSON.parse(e.data)
        const stepId = step.step_id || step.id || `step-${++stepCounter}`
        dispatch({
          type: 'ADD_STEP',
          msgId: asstMsgId,
          step: {
            stepId,
            agent:         step.agent || step.name || 'agent',
            status:        step.status || 'running',
            message:       step.message || '',
            reason:        step.reason || '',
            durationLabel: step.duration_label || '',
            startedAt:     step.started_at || '',
          }
        })
        const agent = String(step.agent || step.name || 'agent').trim()
        const reason = String(step.reason || step.message || '').trim()
        const stepStatus = String(step.status || 'running').toLowerCase()
        const title = ['completed', 'done', 'success'].includes(stepStatus)
          ? `${agent} completed a task`
          : ['failed', 'error'].includes(stepStatus)
            ? `${agent} reported a failure`
            : `${agent} is working`
        dispatch({
          type: 'ADD_PROGRESS',
          msgId: asstMsgId,
          item: {
            id: stepId,
            title,
            detail: reason || '',
            kind: 'step',
            status: step.status || 'running',
          },
        })
        dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { status: 'streaming' } })
      } catch (_) {}
    })

    es.addEventListener('activity', e => {
      try {
        const item = JSON.parse(e.data)
        const title = String(item.title || item.kind || 'Activity').trim()
        const detail = String(item.detail || item.command || '').trim()
        dispatch({
          type: 'ADD_PROGRESS',
          msgId: asstMsgId,
          item: {
            id: item.id || `activity-${Date.now()}`,
            title,
            detail,
            kind: item.kind || 'activity',
            status: item.status || 'running',
            command: item.command || '',
            cwd: item.cwd || '',
            actor: item.actor || '',
            durationLabel: item.duration_label || '',
            exitCode: item.exit_code,
          },
        })
      } catch (_) {}
    })

    es.addEventListener('delta', e => {
      try {
        const d = JSON.parse(e.data)
        if (!d.delta) return
        dispatch({ type: 'APPEND_MSG_CONTENT', id: asstMsgId, delta: String(d.delta) })
        dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { status: 'streaming' } })
      } catch (_) {}
    })

    es.addEventListener('result', e => {
      try {
        const d = JSON.parse(e.data)
        const output = d.final_output || d.output || d.draft_response || d.response || ''
        const awaiting = !!(
          d.awaiting_user_input || d.plan_waiting_for_approval || d.plan_needs_clarification ||
          d.pending_user_input_kind || d.approval_pending_scope || d.pending_user_question ||
          (d.approval_request && Object.keys(d.approval_request).length > 0)
        )
        if (awaiting) {
          const checklist = extractChecklist(d)
          dispatch({
            type: 'SET_AWAITING',
            ctx: {
              runId,
              workflowId: d.workflow_id || runId,
              messageId: asstMsgId,
              prompt: d.pending_user_question || output || 'Waiting for your input.',
              kind:   d.pending_user_input_kind || '',
              scope: d.approval_pending_scope || '',
              approvalRequest: d.approval_request || null,
            }
          })
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { content: output, status: 'awaiting', artifacts: d.artifact_files || [], checklist } })
        } else {
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { content: output, status: 'done', artifacts: d.artifact_files || [], checklist: extractChecklist(d) } })
        }
      } catch (_) {}
    })

    es.addEventListener('done', e => {
      try {
        const d = JSON.parse(e.data)
        if (d.awaiting_user_input || String(d.status).toLowerCase() === 'awaiting_user_input') {
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { status: 'awaiting' } })
        } else {
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { status: d.status === 'failed' ? 'error' : 'done' } })
          dispatch({ type: 'CLEAR_AWAITING' })
        }
      } catch (_) {}
      closeClean()
      dispatch({ type: 'SET_STREAMING', val: false })
      appDispatch({ type: 'SET_STREAMING', streaming: false })
      appDispatch({ type: 'SET_ACTIVE_RUN', runId: null })
    })

    es.addEventListener('error', e => {
      try {
        const d = JSON.parse(e.data)
        dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { content: d.message || 'Run failed.', status: 'error' } })
      } catch (_) {
        dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { status: 'error' } })
      }
      refreshModelInventory(true)
      closeClean()
      dispatch({ type: 'SET_STREAMING', val: false })
      appDispatch({ type: 'SET_STREAMING', streaming: false })
      appDispatch({ type: 'SET_ACTIVE_RUN', runId: null })
    })

    es.onerror = () => {
      if (closed) return
      refreshModelInventory(true)
      dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { status: 'error' } })
      closeClean()
      dispatch({ type: 'SET_STREAMING', val: false })
      appDispatch({ type: 'SET_STREAMING', streaming: false })
      appDispatch({ type: 'SET_ACTIVE_RUN', runId: null })
    }
  }, [apiBase, appDispatch, refreshModelInventory])

  // Re-attach to an active background run when returning to chat view.
  useEffect(() => {
    const activeRunId = String(appState.activeRunId || '').trim()
    if (!activeRunId) return
    if (resumeAttemptedRunRef.current === activeRunId) return
    resumeAttemptedRunRef.current = activeRunId

    let cancelled = false
    ;(async () => {
      try {
        const resp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(activeRunId)}`)
        const data = await resp.json().catch(() => ({}))
        if (cancelled) return
        if (!resp.ok) return
        const status = String(data?.status || '').toLowerCase()
        if (['completed', 'failed', 'cancelled'].includes(status)) {
          appDispatch({ type: 'SET_STREAMING', streaming: false })
          appDispatch({ type: 'SET_ACTIVE_RUN', runId: null })
          return
        }

        let asstMsgId = ''
        const existing = (chat.messages || []).find(m => String(m.runId || '') === activeRunId)
        if (existing?.id) {
          asstMsgId = existing.id
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { status: status === 'awaiting_user_input' ? 'awaiting' : 'streaming' } })
        } else {
          asstMsgId = `a-${activeRunId}-resume`
          dispatch({
            type: 'ADD_MSG',
            msg: {
              id: asstMsgId,
              role: 'assistant',
              content: '',
              steps: [],
              progress: [],
              status: status === 'awaiting_user_input' ? 'awaiting' : 'thinking',
              runId: activeRunId,
              runStartedAt: data?.started_at || new Date().toISOString(),
              mode: chat.mode,
              modeLabel: modeLabel(chat.mode),
              ts: new Date(),
            },
          })
        }
        dispatch({ type: 'SET_RUN', id: activeRunId })
        dispatch({ type: 'SET_STREAMING', val: status !== 'awaiting_user_input' })
        appDispatch({ type: 'SET_STREAMING', streaming: status !== 'awaiting_user_input' })
        openStream(activeRunId, asstMsgId)
      } catch (_) {
      }
    })()

    return () => { cancelled = true }
  }, [appState.activeRunId, apiBase, openStream, chat.messages, chat.mode, appDispatch])

  // ── Stop run ────────────────────────────────────────────────────────────────
  const stopRun = useCallback(async () => {
    esRef.current?.close()
    // Mark the in-progress bubble as done so it doesn't stay stuck in "Running"
    const activeMsg = chat.messages.find(m => m.status === 'streaming' || m.status === 'thinking')
    if (activeMsg) {
      dispatch({ type: 'UPD_MSG', id: activeMsg.id, patch: { status: 'done' } })
    }
    dispatch({ type: 'CLEAR_AWAITING' })
    if (chat.activeRunId) {
      await fetch(`${apiBase}/api/runs/stop`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: chat.activeRunId })
      }).catch(() => {})
    }
    dispatch({ type: 'SET_STREAMING', val: false })
    appDispatch({ type: 'SET_STREAMING', streaming: false })
    appDispatch({ type: 'SET_ACTIVE_RUN', runId: null })
  }, [chat.activeRunId, chat.messages, apiBase, appDispatch])

  const submitSkillApproval = useCallback(async (scope, note = '') => {
    const ctx = chat.awaitingContext || {}
    const request = (ctx.approvalRequest && typeof ctx.approvalRequest === 'object') ? ctx.approvalRequest : {}
    const metadata = (request.metadata && typeof request.metadata === 'object') ? request.metadata : {}
    const skillId = String(metadata.skill_id || '').trim()
    const sessionId = String(metadata.session_id || '').trim()
    if (!skillId) throw new Error('Missing skill id for approval.')

    const response = await fetch(`${apiBase}/api/marketplace/skills/${encodeURIComponent(skillId)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scope,
        note: String(note || '').trim() || `Approved ${String(metadata.skill_slug || skillId)} from the desktop chat UI (${scope}).`,
        session_id: sessionId,
      }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok || !data.ok) {
      throw new Error(data.error || data.detail || response.statusText)
    }

    const reply = scope === 'always'
      ? 'approve always'
      : scope === 'session'
        ? 'approve for this session'
        : 'approve once'
    await send(reply, true)
  }, [apiBase, chat.awaitingContext, send])

  const handleKey = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send() }
  }

  const isOnline = appState.backendStatus === 'running'
  const studioModelLabel = (() => {
    if (selectedModelMeta.model) return `Selected · ${selectedModelMeta.label}`
    const provider = String(modelInventory?.configured_provider || '').trim()
    const model = String(modelInventory?.configured_model || '').trim()
    if (provider && model) return `Auto · ${resolveSelectedModel(`${provider}/${model}`).label}`
    return 'Auto · Backend default'
  })()
  const attachFiles = useCallback(async () => {
    const paths = await window.kendrAPI?.dialog.openFiles([{ name: 'All Files', extensions: ['*'] }])
    if (!Array.isArray(paths) || !paths.length) return
    setAttachments((prev) => {
      const seen = new Set(prev.map(item => item.path))
      const next = [...prev]
      for (const filePath of paths) {
        if (seen.has(filePath)) continue
        next.push({ path: filePath, type: detectAttachmentType(filePath), name: basename(filePath) })
        seen.add(filePath)
      }
      return next
    })
  }, [])
  const attachFolder = useCallback(async () => {
    const dir = await window.kendrAPI?.dialog.openDirectory()
    if (!dir) return
    setAttachments((prev) => prev.some(item => item.path === dir)
      ? prev
      : [...prev, { path: dir, type: 'folder', name: basename(dir) }])
  }, [])
  const removeAttachment = useCallback((path) => {
    setAttachments((prev) => prev.filter(item => item.path !== path))
  }, [])
  const handlePaste = useCallback(async (e) => {
    const items = Array.from(e.clipboardData?.items || [])
    const imageItems = items.filter(item => item.kind === 'file' && String(item.type || '').startsWith('image/'))
    if (!imageItems.length) return
    e.preventDefault()
    const api = window.kendrAPI
    const saved = []
    for (const item of imageItems) {
      const file = item.getAsFile()
      if (!file) continue
      try {
        const dataUrl = await readBlobAsDataUrl(file)
        const result = await api?.clipboard?.saveImage({
          dataUrl,
          name: file.name ? file.name.replace(/\.[^.]+$/, '') : 'pasted-screenshot',
        })
        if (result?.path) {
          saved.push({
            path: result.path,
            type: 'image',
            name: basename(result.path),
          })
        }
      } catch (_) {}
    }
    if (!saved.length) return
    setAttachments((prev) => {
      const seen = new Set(prev.map(item => item.path))
      const next = [...prev]
      for (const item of saved) {
        if (seen.has(item.path)) continue
        next.push(item)
        seen.add(item.path)
      }
      return next
    })
  }, [])
  const MODES = [
    { id: 'chat',     label: '💬 Chat' },
    { id: 'agent',    label: '✨ Agent' },
    { id: 'research', label: '🔬 Deep Research' },
  ]

  return (
    <div className={`kc-panel${fullWidth ? ' kc-panel--full' : ''}`}>
      {/* ── Header ── */}
      {!hideHeader && <div className="kc-header">
        <div className="kc-logo">K<span>endr</span></div>
        <div className="kc-header-model" title={studioModelLabel}>
          <span className={`kc-header-model-dot ${selectedModelMeta.isLocal || String(modelInventory?.configured_provider || '').toLowerCase() === 'ollama' ? 'local' : ''}`} />
          <span>{studioModelLabel}</span>
          {!studioMode && appState.projectRoot && <span className="kc-header-model-project">{basename(appState.projectRoot)}</span>}
        </div>
        <div className="kc-header-status">
          <span className={`kc-dot ${isOnline ? 'kc-dot--on' : ''}`} />
          <span className="kc-header-status-text">{isOnline ? 'connected' : appState.backendStatus}</span>
        </div>
        <div className="kc-header-actions">
          <button className="kc-icon-btn" title="Chat history" onClick={() => setShowHistory(v => !v)}>
            <HistoryIcon />
          </button>
          <button className="kc-icon-btn" title="New chat" onClick={newChat}>
            <ClearIcon />
          </button>
          {!fullWidth && (
            <button className="kc-icon-btn" title="Close" onClick={() => appDispatch({ type: 'TOGGLE_CHAT' })}>✕</button>
          )}
        </div>
      </div>}

      {/* ── Mode pills ── */}
      <div className="kc-mode-bar">
        {MODES.map(m => (
          <button
            key={m.id}
            className={`kc-mode-pill ${chat.mode === m.id ? 'kc-mode-pill--active' : ''} ${m.id === 'agent' && !selectedModelAgentCapable ? 'kc-mode-pill--disabled' : ''}`}
            onClick={() => { if (m.id === 'agent' && !selectedModelAgentCapable) return; dispatch({ type: 'SET_MODE', mode: m.id }) }}
            title={m.id === 'agent' && !selectedModelAgentCapable ? 'Selected model cannot run as agent.' : ''}
          >{m.label}</button>
        ))}
      </div>

      {/* ── Deep Research Panel ── */}
      {chat.mode === 'research' && (
        <DeepResearchPanel dr={dr} updateDr={updateDr} />
      )}

      {/* ── Messages ── */}
      <div className="kc-messages">
        {chat.messages.length === 0 && <WelcomeScreen onSuggest={s => { setInput(s); inputRef.current?.focus() }} />}

        {chat.messages.map(msg =>
          msg.role === 'user'
            ? <UserMessage key={msg.id} msg={msg} />
            : <AssistantMessage key={msg.id} msg={msg} />
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Agent approval modal ── */}
      {chat.awaitingContext && (
        <AgentApprovalModal
          ctx={chat.awaitingContext}
          value={resumeInput}
          onChange={setResumeInput}
          onSend={() => send(resumeInput, true)}
          onQuickReply={r => send(r, true)}
          onSkillApprove={submitSkillApproval}
          onStop={stopRun}
          onDismiss={() => { dispatch({ type: 'CLEAR_AWAITING' }); setResumeInput('') }}
        />
      )}

      {/* ── History drawer ── */}
      {showHistory && (
        <div className="kc-history-overlay" onClick={e => e.target === e.currentTarget && setShowHistory(false)}>
          <div className="kc-history-drawer">
            <div className="kc-history-hdr">
              <span>Chat History</span>
              <button className="kc-icon-btn" onClick={() => setShowHistory(false)}>✕</button>
            </div>
            <button className="kc-history-new-btn" onClick={newChat}>+ New Chat</button>
            <div className="kc-history-list">
              <HistoryList sessions={sessions} onLoad={loadSession} onDelete={deleteSession} />
            </div>
            <div className="kc-history-footer">
              <ClockIcon size={12} />
              {(appState.settings?.chatHistoryRetentionDays ?? 14) > 0
                ? `Auto-deleted after ${appState.settings?.chatHistoryRetentionDays ?? 14} days · configure in Settings`
                : 'History kept forever · configure in Settings'}
            </div>
          </div>
        </div>
      )}

      {stickyChecklist.length > 0 && (
        <StickyChecklist
          checklist={stickyChecklist}
          title={stickyChecklistMsg?.status === 'awaiting' ? 'Checklist waiting' : 'Checklist'}
        />
      )}

      {/* ── Input area ── */}
      <div className="kc-input-area">
        <div className="kc-attach-bar">
          <div className="kc-attach-actions">
            <button className="kc-attach-btn" onClick={attachFiles}>+ Files</button>
            {studioMode && <button className="kc-attach-btn" onClick={attachFolder}>+ Folder</button>}
            {chat.mode === 'agent' ? (
              <span
                className={`kc-mcp-indicator${mcpEnabled && mcpUndiscovered > 0 ? ' kc-mcp-indicator--warn' : ''}`}
                title={mcpUndiscovered > 0
                  ? `${mcpUndiscovered} server${mcpUndiscovered !== 1 ? 's have' : ' has'} no tools discovered yet — open MCP Settings to run discovery`
                  : `${mcpServerCount} MCP server${mcpServerCount !== 1 ? 's' : ''} active`}
              >
                🔌 MCP {mcpServerCount > 0 ? `· ${mcpServerCount}` : ''}{mcpUndiscovered > 0 ? ' ⚠' : ''}
              </span>
            ) : (
              <button
                className={`kc-attach-btn kc-mcp-toggle${mcpEnabled ? ' kc-mcp-toggle--on' : ''}${mcpEnabled && mcpUndiscovered > 0 ? ' kc-mcp-toggle--warn' : ''}`}
                onClick={() => setMcpEnabled(v => !v)}
                title={
                  mcpEnabled && mcpUndiscovered > 0
                    ? `${mcpUndiscovered} server${mcpUndiscovered !== 1 ? 's have' : ' has'} no tools discovered — open MCP Settings to run discovery`
                    : mcpEnabled ? 'Disable MCP tools for this chat' : `Enable MCP tools (${mcpServerCount} server${mcpServerCount !== 1 ? 's' : ''} available)`
                }
              >
                🔌 MCP {mcpEnabled ? 'ON' : 'OFF'}{mcpEnabled && mcpUndiscovered > 0 ? ' ⚠' : ''}
              </button>
            )}
          </div>
          {!!attachments.length && (
            <div className="kc-attach-list">
              {attachments.map(item => (
                <span key={item.path} className="kc-attach-chip" title={item.path}>
                  <span>
                    {item.type === 'folder' ? '📁' : item.type === 'image' ? '🖼' : '📄'} {item.name}
                  </span>
                  <button onClick={() => removeAttachment(item.path)}>×</button>
                </span>
              ))}
            </div>
          )}
        </div>
        {!studioMode && appState.projectRoot && (
          <div className="kc-project-badge">
            <span>📁 {appState.projectRoot.split(/[\\/]/).pop()}</span>
          </div>
        )}
        <div className="kc-context-row">
          <div className="kc-context-badge" title={`Estimated context usage: ${estimatedContextTokens} / ${contextLimit} tokens (${contextPct}%)`}>
            <span className="kc-context-icon">🧠</span>
            <span className="kc-context-text">{estimatedContextTokens.toLocaleString()} / {contextLimit.toLocaleString()} ctx</span>
            <div className="kc-context-bar">
              <div
                className={`kc-context-fill${contextPct >= 90 ? ' full' : contextPct >= 75 ? ' warn' : ''}`}
                style={{ width: `${contextPct}%` }}
              />
            </div>
          </div>
          <button className="kc-attach-btn" onClick={compactContext} title="Compact context and continue in a fresh backend session">
            Compact
          </button>
        </div>
        <div className="kc-input-row">
          <textarea
            ref={inputRef}
            className="kc-input"
            placeholder={
              chat.mode === 'research'  ? 'Describe the deep research task, scope, and output you want…'  :
              chat.mode === 'security'  ? 'Describe the target and scope…'     :
              chat.mode === 'agent'     ? 'Ask the agent to investigate, reason step by step, and do the detailed work… (Ctrl+Enter)' :
              'Ask a direct question… (Ctrl+Enter)'
            }
            value={input}
            onChange={e => setInput(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={handleKey}
            rows={3}
            disabled={chat.streaming}
          />
          <button
            className={`kc-send-btn ${chat.streaming ? 'kc-send-btn--stop' : ''}`}
            onClick={chat.streaming ? () => stopRun() : () => send()}
            disabled={!chat.streaming && !input.trim()}
            title={chat.streaming ? 'Stop (sends cancellation)' : 'Send (Ctrl+Enter)'}
          >
            {chat.streaming ? <StopIcon /> : <SendIcon />}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Deep Research Panel ──────────────────────────────────────────────────────
function DeepResearchPanel({ dr, updateDr }) {
  const api = window.kendrAPI

  const toggleFormat = (fmt) => {
    const cur = dr.outputFormats
    const next = cur.includes(fmt) ? cur.filter(f => f !== fmt) : [...cur, fmt]
    updateDr({ outputFormats: next })
  }

  const toggleSource = (src) => {
    const cur = dr.sources
    const next = cur.includes(src) ? cur.filter(s => s !== src) : [...cur, src]
    updateDr({ sources: next })
  }

  const addLocalPath = async () => {
    const dir = await api?.dialog.openDirectory()
    if (dir && !dr.localPaths.includes(dir)) {
      updateDr({ localPaths: [...dr.localPaths, dir] })
    }
  }

  const removeLocalPath = (p) => updateDr({ localPaths: dr.localPaths.filter(x => x !== p) })

  return (
    <div className="dr-panel">
      <div className="dr-panel-header" onClick={() => updateDr({ collapsed: !dr.collapsed })}>
        <span className="dr-panel-title">🔬 Deep Research Settings</span>
        <div className="dr-summary">
          <span className="dr-sum-pill">~{dr.pages}p</span>
          <span className="dr-sum-pill">{dr.citationStyle.toUpperCase()}</span>
          <span className="dr-sum-pill">{dr.outputFormats.join('·')}</span>
          {!dr.webSearchEnabled && <span className="dr-sum-pill dr-sum-warn">Local only</span>}
        </div>
        <span className="dr-collapse-btn">{dr.collapsed ? '▸' : '▾'}</span>
      </div>

      {!dr.collapsed && (
        <div className="dr-body">
          {/* Row 1 */}
          <div className="dr-grid">
            <div className="dr-field">
              <label className="dr-label">Approx. Length</label>
              <select className="dr-select" value={dr.pages} onChange={e => updateDr({ pages: +e.target.value })}>
                <option value={10}>~10 pages</option>
                <option value={25}>~25 pages</option>
                <option value={50}>~50 pages</option>
                <option value={100}>~100 pages</option>
              </select>
              <div className="dr-note">Aiming near this length; citations and formatting can shift the final page count.</div>
            </div>
            <div className="dr-field">
              <label className="dr-label">Citation Style</label>
              <select className="dr-select" value={dr.citationStyle} onChange={e => updateDr({ citationStyle: e.target.value })}>
                <option value="apa">APA</option>
                <option value="mla">MLA</option>
                <option value="chicago">Chicago</option>
                <option value="ieee">IEEE</option>
              </select>
            </div>
            <div className="dr-field">
              <label className="dr-label">Date Range</label>
              <select className="dr-select" value={dr.dateRange} onChange={e => updateDr({ dateRange: e.target.value })}>
                <option value="all_time">All time</option>
                <option value="1y">Last year</option>
                <option value="2y">Last 2 years</option>
                <option value="5y">Last 5 years</option>
              </select>
            </div>
            <div className="dr-field">
              <label className="dr-label">Max Sources</label>
              <input className="dr-input-sm" type="number" min={0} step={10} value={dr.maxSources}
                onChange={e => updateDr({ maxSources: +e.target.value })} placeholder="0 = auto" />
            </div>
          </div>

          {/* Row 2 */}
          <div className="dr-grid" style={{ marginTop: 8 }}>
            <div className="dr-field">
              <label className="dr-label">Output Formats</label>
              <div className="dr-checks">
                {['pdf','docx','html','md'].map(f => (
                  <label key={f} className="dr-check">
                    <input type="checkbox" checked={dr.outputFormats.includes(f)} onChange={() => toggleFormat(f)} />
                    {f.toUpperCase()}
                  </label>
                ))}
              </div>
            </div>
            <div className="dr-field">
              <label className="dr-label">Source Families</label>
              <div className="dr-checks">
                <label className="dr-check dr-check--web">
                  <input type="checkbox" checked={dr.webSearchEnabled}
                    onChange={e => updateDr({ webSearchEnabled: e.target.checked })} />
                  🌐 Web Search
                </label>
                {[['web','Web'],['arxiv','Academic'],['patents','Patents'],['news','News'],['reddit','Community']].map(([v,l]) => (
                  <label key={v} className="dr-check" style={{ opacity: dr.webSearchEnabled ? 1 : 0.4 }}>
                    <input type="checkbox" checked={dr.sources.includes(v)} disabled={!dr.webSearchEnabled}
                      onChange={() => toggleSource(v)} />
                    {l}
                  </label>
                ))}
              </div>
            </div>
            <div className="dr-field">
              <label className="dr-label">Quality Gates</label>
              <div className="dr-checks">
                <label className="dr-check">
                  <input type="checkbox" checked={dr.plagiarismCheck} onChange={e => updateDr({ plagiarismCheck: e.target.checked })} />
                  Plagiarism Check
                </label>
                <label className="dr-check">
                  <input type="checkbox" checked={dr.checkpointing} onChange={e => updateDr({ checkpointing: e.target.checked })} />
                  Checkpointing
                </label>
              </div>
            </div>
          </div>

          {/* Local paths */}
          <div className="dr-field" style={{ marginTop: 8 }}>
            <label className="dr-label">Local Folders / Files</label>
            <div className="dr-path-row">
              <button className="dr-action-btn" onClick={addLocalPath}>+ Browse Folder</button>
            </div>
            {dr.localPaths.length > 0 && (
              <div className="dr-chips">
                {dr.localPaths.map(p => (
                  <span key={p} className="dr-chip">
                    <span>📁 {p.split(/[\\/]/).slice(-2).join('/')}</span>
                    <button onClick={() => removeLocalPath(p)}>✕</button>
                  </span>
                ))}
              </div>
            )}
            <div className="dr-note">Folders are read recursively by the backend (local machine paths).</div>
          </div>

          {/* Explicit links */}
          <div className="dr-field" style={{ marginTop: 8 }}>
            <label className="dr-label">Explicit Content Links</label>
            <textarea
              className="dr-textarea"
              rows={3}
              placeholder={"https://example.com/report\nhttps://example.com/dataset"}
              value={dr.links}
              onChange={e => updateDr({ links: e.target.value })}
              disabled={!dr.webSearchEnabled}
            />
            <div className="dr-note">
              {dr.webSearchEnabled
                ? 'These exact URLs will be fetched as part of the report.'
                : 'Enable Web Search to use explicit links.'}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Welcome screen ───────────────────────────────────────────────────────────
function WelcomeScreen({ onSuggest }) {
  const SUGGESTIONS = [
    'Summarize the attached files for me',
    'Explain this topic simply',
    'Investigate this problem step by step',
    'Run a security assessment',
    'Write a detailed technical report',
    'Compare two approaches and recommend one',
  ]
  return (
    <div className="kc-welcome">
      <div className="kc-welcome-logo">⚡</div>
      <h2 className="kc-welcome-title">Kendr Studio</h2>
      <p className="kc-welcome-sub">Use Chat for direct answers. Use Agent when you want the assistant to do the detailed work and reason through the task.</p>
      <div className="kc-suggestions">
        {SUGGESTIONS.map(s => (
          <button key={s} className="kc-suggest" onClick={() => onSuggest(s)}>{s}</button>
        ))}
      </div>
    </div>
  )
}

// ─── User message ─────────────────────────────────────────────────────────────
function UserMessage({ msg }) {
  const attachments = Array.isArray(msg.attachments) ? msg.attachments : []
  const imageAttachments = attachments.filter((item) => item?.type === 'image')
  return (
    <div className="kc-row kc-row--user">
      <div className="kc-bubble kc-bubble--user">
        {msg.modeLabel && (
          <div className="kc-mode-stamp">
            <span className={`kc-mode-stamp-chip kc-mode-stamp-chip--${String(msg.mode || 'chat')}`}>{msg.modeLabel}</span>
          </div>
        )}
        <div className="kc-bubble-text">{msg.content}</div>
        {attachments.length > 0 && (
          <div className="kc-msg-attachments">
            {imageAttachments.length > 0 && (
              <div className="kc-msg-image-grid">
                {imageAttachments.map((item) => {
                  const src = attachmentPreviewSrc(item)
                  return (
                    <div key={`img-${item.path}`} className="kc-msg-image-card" title={item.path}>
                      {src ? <img src={src} alt={item.name || 'attached image'} className="kc-msg-image" /> : <div className="kc-msg-image-fallback">🖼</div>}
                      <div className="kc-msg-image-name">{item.name}</div>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="kc-msg-attach-list">
              {attachments.map((item) => (
                <span key={item.path} className="kc-msg-attach-chip" title={item.path}>
                  {item.type === 'folder' ? '📁' : item.type === 'image' ? '🖼' : '📄'} {item.name}
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="kc-bubble-ts">{formatTs(msg.ts)}</div>
      </div>
      <div className="kc-avatar kc-avatar--user">👤</div>
    </div>
  )
}

// ─── Assistant message ────────────────────────────────────────────────────────
function AssistantMessage({ msg }) {
  const [copied, setCopied] = useState(false)
  const [nowMs, setNowMs] = useState(Date.now())
  const copy = () => { navigator.clipboard.writeText(msg.content); setCopied(true); setTimeout(() => setCopied(false), 1500) }
  useEffect(() => {
    if (!msg?.runId) return
    if (!['thinking', 'streaming', 'awaiting'].includes(String(msg?.status || ''))) return
    const timer = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [msg?.runId, msg?.status])
  const elapsedSeconds = msg?.runId ? Math.max(0, Math.floor((nowMs - new Date(msg.runStartedAt || msg.ts || Date.now()).getTime()) / 1000)) : 0
  const progress = Array.isArray(msg.progress) ? msg.progress : []
  const shellCard = shellCardFromProgress(progress)
  const visibleProgress = progress.filter((item) => !isShellProgressItem(item))
  const checklist = Array.isArray(msg.checklist) ? msg.checklist : []
  const blockerChips = inferExecutionBlockers({ msg, shellCard, progress: visibleProgress, checklist })
  const progressSummary = (() => {
    if (!visibleProgress.length) return ''
    let searches = 0
    let files = 0
    for (const item of visibleProgress) {
      const kind = String(item.kind || '').toLowerCase()
      const text = `${item.title || ''} ${item.detail || ''}`.toLowerCase()
      if (kind.includes('search') || /\b(search|query|grep|rg|ripgrep)\b/.test(text)) searches += 1
      if (kind.includes('file') || /\b(file|read|scan|inspect|inventory)\b/.test(text)) files += 1
    }
    const parts = []
    if (files) parts.push(`${files} file${files === 1 ? '' : 's'}`)
    if (searches) parts.push(`${searches} search${searches === 1 ? '' : 'es'}`)
    return parts.length ? `Exploring ${parts.join(', ')}` : ''
  })()

  return (
    <div className="kc-row kc-row--assistant">
      <div className="kc-avatar kc-avatar--kendr">K</div>
      <div className="kc-bubble kc-bubble--assistant">

        {/* Run hero */}
        {msg.runId && (
          <div className="kc-run-hero">
            <div className="kc-run-eyebrow">Run</div>
            <div className="kc-run-id">{msg.runId}</div>
            {msg.modeLabel && (
              <div className={`kc-run-mode kc-run-mode--${String(msg.mode || 'chat')}`}>{msg.modeLabel}</div>
            )}
            {msg.runId && <div className="kc-run-elapsed">⏱ {formatDuration(elapsedSeconds)}</div>}
            <div className={`kc-run-badge kc-run-badge--${msg.status || 'thinking'}`}>
              {{ thinking: 'Thinking', streaming: 'Running', awaiting: 'Awaiting Input', done: 'Done', error: 'Error' }[msg.status] || 'Thinking'}
            </div>
          </div>
        )}

        {/* Thinking */}
        {msg.status === 'thinking' && (
          <div className="kc-thinking">
            <span className="kc-typing-dot" />
            <span className="kc-typing-dot" />
            <span className="kc-typing-dot" />
            {msg.statusText && <span className="kc-thinking-text">{msg.statusText}</span>}
          </div>
        )}

        {shellCard && (
          <div className={`kc-shell-card kc-shell-card--${shellCard.status || 'running'}`}>
            <div className="kc-shell-card-head">
              <span className="kc-shell-card-label">Shell</span>
              <span className="kc-shell-card-title">{shellCard.title}</span>
            </div>
            {shellCard.command && (
              <pre className="kc-shell-card-code"><code>$ {shellCard.command}</code></pre>
            )}
            {shellCard.output && (
              <pre className="kc-shell-card-output"><code>{shellCard.output}</code></pre>
            )}
            {(shellCard.cwd || shellCard.durationLabel || (shellCard.exitCode !== null && shellCard.exitCode !== undefined)) && (
              <div className="kc-shell-card-meta">
                {shellCard.cwd && <span>{shellCard.cwd}</span>}
                {shellCard.durationLabel && <span>{shellCard.durationLabel}</span>}
                {shellCard.exitCode !== null && shellCard.exitCode !== undefined && <span>exit {shellCard.exitCode}</span>}
              </div>
            )}
          </div>
        )}

        {blockerChips.length > 0 && (
          <div className="kc-blocker-strip">
            {blockerChips.map((item) => (
              <span key={item.key} className={`kc-blocker-chip kc-blocker-chip--${item.tone || 'warn'}`}>{item.label}</span>
            ))}
          </div>
        )}

        {/* Codex-style worklog */}
        {msg.runId && (['thinking', 'streaming', 'awaiting'].includes(String(msg.status || '')) || visibleProgress.length > 0) && (
          <div className="kc-worklog">
            <div className="kc-worklog-head">Working for {formatDuration(elapsedSeconds)}</div>
            {progressSummary && <div className="kc-worklog-summary">{progressSummary}</div>}
            <div className="kc-worklog-items">
              {visibleProgress.slice(0, 6).map(item => (
                <div key={item.id} className="kc-worklog-item">
                  <div className="kc-worklog-title">{item.title}</div>
                  {item.detail && <div className="kc-worklog-detail">{item.detail}</div>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step timeline */}
        {msg.steps?.length > 0 && (
          <div className="kc-steps">
            {msg.steps.map(step => <StepCard key={step.stepId} step={step} />)}
          </div>
        )}

        {checklist.length > 0 && (
          <ChecklistCard checklist={checklist} />
        )}

        {/* Final content */}
        {msg.content && msg.status !== 'error' && (
          <div className="kc-content">
            <div className="kc-content-actions">
              <button className="kc-copy-btn" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
            </div>
            <MarkdownRenderer
              content={msg.content}
              isStreaming={['thinking', 'streaming'].includes(String(msg.status || ''))}
            />
          </div>
        )}

        {/* Error */}
        {msg.status === 'error' && msg.content && (
          <div className="kc-error-msg">⚠ {msg.content}</div>
        )}

        {/* Awaiting */}
        {msg.status === 'awaiting' && (
          <div className="kc-awaiting-note">⏳ Waiting for your reply above…</div>
        )}

        <div className="kc-bubble-ts">{formatTs(msg.ts)}</div>
      </div>
    </div>
  )
}

function ChecklistCard({ checklist }) {
  return (
    <div className="kc-checklist-card">
      <div className="kc-checklist-title">Checklist</div>
      <div className="kc-checklist-list">
        {checklist.map((item) => (
          <ChecklistItem key={`${item.step}-${item.title}`} item={item} />
        ))}
      </div>
    </div>
  )
}

function StickyChecklist({ checklist, title }) {
  return (
    <div className="kc-sticky-checklist">
      <div className="kc-sticky-checklist-head">
        <span>{title}</span>
        <span>{checklist.filter(item => item.done).length}/{checklist.length}</span>
      </div>
      <div className="kc-checklist-list">
        {checklist.map((item) => (
          <ChecklistItem key={`sticky-${item.step}-${item.title}`} item={item} compact />
        ))}
      </div>
    </div>
  )
}

function ChecklistItem({ item, compact = false }) {
  const state = normalizeChecklistStatus(item.status)
  const icon = state === 'completed' ? '✓'
    : state === 'skipped' ? '↷'
    : state === 'running' ? '…'
    : state === 'awaiting' ? '!'
    : state === 'failed' || state === 'blocked' ? '✗'
    : '·'
  const detail = String(item.detail || item.reason || item.stdout || item.stderr || '').trim()
  const doneLike = state === 'completed' || state === 'skipped'

  return (
    <div className={`kc-checklist-item kc-checklist-item--${state}${doneLike ? ' kc-checklist-item--done' : ''}`}>
      <div className="kc-checklist-mark">{icon}</div>
      <div className="kc-checklist-body">
        <div className="kc-checklist-row">
          <span className="kc-checklist-step">{item.step}.</span>
          <span className="kc-checklist-text">{item.title}</span>
        </div>
        {!compact && item.command && <div className="kc-checklist-command">$ {item.command}</div>}
        {detail && <div className="kc-checklist-detail">{detail}</div>}
      </div>
    </div>
  )
}

function parseMcpAgentMeta(agentName) {
  const raw = String(agentName || '').trim()
  if (!raw.startsWith('mcp_') || !raw.endsWith('_agent')) return null
  const inner = raw.slice(4, -6)
  const parts = inner.split('_')
  if (!parts.length) return null
  const server = parts[0] || ''
  const tool = parts.slice(1).join('_') || ''
  return {
    server,
    tool,
    serverLabel: server.replace(/_/g, ' '),
    toolLabel: tool.replace(/_/g, ' '),
  }
}

// ─── Step card ────────────────────────────────────────────────────────────────
function StepCard({ step }) {
  const [open, setOpen] = useState(false)
  const cls = step.status === 'completed' || step.status === 'success' ? 'done'
            : step.status === 'failed'    || step.status === 'error'   ? 'failed'
            : step.status === 'running'                                ? 'running'
            : 'pending'
  const mcpMeta = parseMcpAgentMeta(step.agent)

  const ICON = { done: '✓', failed: '✗', running: '●', pending: '·' }

  return (
    <div className={`kc-step kc-step--${cls}`}>
      <div className="kc-step-dot">{ICON[cls]}</div>
      <div className="kc-step-inner">
        <div className="kc-step-header" onClick={() => (step.reason || step.message) && setOpen(o => !o)}>
          {mcpMeta ? (
            <>
              <span className="kc-step-agent kc-step-agent--mcp">🔌 MCP</span>
              <span className="kc-step-chip">{mcpMeta.serverLabel}</span>
              <span className="kc-step-agent">{mcpMeta.toolLabel || step.agent}</span>
            </>
          ) : (
            <span className="kc-step-agent">{step.agent}</span>
          )}
          {step.message && <span className="kc-step-msg">{step.message.slice(0, 80)}</span>}
          {step.durationLabel && <span className="kc-step-dur">{step.durationLabel}</span>}
          {(step.reason || step.message) && (
            <span className="kc-step-toggle">{open ? '▾' : '▸'}</span>
          )}
        </div>
        {mcpMeta && (
          <div className="kc-step-reason kc-step-reason--inline">Ran MCP tool `{mcpMeta.toolLabel}` via `{mcpMeta.serverLabel}`.</div>
        )}
        {open && step.reason && (
          <div className="kc-step-reason">{step.reason}</div>
        )}
      </div>
    </div>
  )
}

// ─── Markdown renderer ────────────────────────────────────────────────────────
function MarkdownRenderer({ content, isStreaming = false }) {
  if (isStreaming) {
    return (
      <div className="kc-md kc-md--live">
        <pre className="kc-md-live-text">{String(content || '')}</pre>
      </div>
    )
  }

  const blocks = parseMarkdown(content || '')
  return (
    <div className="kc-md">
      {blocks.map((b, i) => (
        <MarkdownBlock key={`${b.type}-${i}`} block={b} />
      ))}
    </div>
  )
}

function MarkdownBlock({ block }) {
  if (block.type === 'code') return <CodeBlock lang={block.lang} code={block.code} />
  if (block.type === 'heading') {
    const HeadingTag = `h${Math.min(6, Math.max(1, Number(block.level) || 1))}`
    return (
      <HeadingTag className={`kc-md-heading kc-md-heading--h${block.level}`}>
        <InlineText text={block.text} />
      </HeadingTag>
    )
  }
  if (block.type === 'ol') {
    return (
      <ol className="kc-md-list kc-md-list--ol" start={block.start || 1}>
        {block.items.map((item, idx) => (
          <li key={idx}><InlineText text={item} /></li>
        ))}
      </ol>
    )
  }
  if (block.type === 'ul') {
    return (
      <ul className="kc-md-list kc-md-list--ul">
        {block.items.map((item, idx) => (
          <li key={idx}><InlineText text={item} /></li>
        ))}
      </ul>
    )
  }
  if (block.type === 'quote') {
    return (
      <blockquote className="kc-md-quote">
        {block.lines.map((line, idx) => (
          <p key={idx}><InlineText text={line} /></p>
        ))}
      </blockquote>
    )
  }
  return (
    <p className="kc-md-paragraph">
      <InlineText text={block.text} />
    </p>
  )
}

function parseMarkdown(content) {
  const lines = String(content || '').replace(/\r\n/g, '\n').split('\n')
  const blocks = []
  let i = 0

  const isBlockStart = (line) => (
    /^```/.test(line)
    || /^(#{1,6})\s+/.test(line)
    || /^>\s?/.test(line)
    || /^\d+\.\s+/.test(line)
    || /^[-*]\s+/.test(line)
  )

  while (i < lines.length) {
    const line = lines[i]

    if (!line.trim()) { i += 1; continue }

    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, '').trim()
      i += 1
      const codeLines = []
      while (i < lines.length && !/^```/.test(lines[i])) {
        codeLines.push(lines[i])
        i += 1
      }
      if (i < lines.length && /^```/.test(lines[i])) i += 1
      blocks.push({ type: 'code', lang, code: codeLines.join('\n').trimEnd() })
      continue
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/)
    if (headingMatch) {
      blocks.push({ type: 'heading', level: headingMatch[1].length, text: headingMatch[2] })
      i += 1
      continue
    }

    if (/^>\s?/.test(line)) {
      const quoteLines = []
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ''))
        i += 1
      }
      blocks.push({ type: 'quote', lines: quoteLines })
      continue
    }

    const ordered = line.match(/^(\d+)\.\s+(.+)$/)
    if (ordered) {
      const items = []
      const start = Number(ordered[1]) || 1
      while (i < lines.length) {
        const m = lines[i].match(/^\d+\.\s+(.+)$/)
        if (!m) break
        items.push(m[1])
        i += 1
      }
      blocks.push({ type: 'ol', start, items })
      continue
    }

    if (/^[-*]\s+/.test(line)) {
      const items = []
      while (i < lines.length) {
        const m = lines[i].match(/^[-*]\s+(.+)$/)
        if (!m) break
        items.push(m[1])
        i += 1
      }
      blocks.push({ type: 'ul', items })
      continue
    }

    const para = []
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      para.push(lines[i].trim())
      i += 1
    }
    blocks.push({ type: 'paragraph', text: para.join(' ') })
  }

  return blocks
}

function InlineText({ text }) {
  const src = String(text || '')
  const nodes = []
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\((https?:\/\/[^\s)]+)\))/g
  let last = 0
  let match
  while ((match = re.exec(src)) !== null) {
    if (match.index > last) {
      nodes.push(src.slice(last, match.index))
    }
    const token = match[0]
    if (token.startsWith('**') && token.endsWith('**')) {
      nodes.push(<strong key={`b-${match.index}`}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('*') && token.endsWith('*')) {
      nodes.push(<em key={`i-${match.index}`}>{token.slice(1, -1)}</em>)
    } else if (token.startsWith('`') && token.endsWith('`')) {
      nodes.push(<code key={`c-${match.index}`} className="kc-inline-code">{token.slice(1, -1)}</code>)
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/)
      if (linkMatch) {
        nodes.push(
          <a
            key={`a-${match.index}`}
            href={linkMatch[2]}
            target="_blank"
            rel="noreferrer"
            className="kc-md-link"
          >
            {linkMatch[1]}
          </a>
        )
      } else {
        nodes.push(token)
      }
    }
    last = match.index + token.length
  }
  if (last < src.length) nodes.push(src.slice(last))
  return <>{nodes}</>
}

function CodeBlock({ lang, code }) {
  const [copied, setCopied] = useState(false)
  const copy = () => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500) }
  return (
    <div className="kc-code-block">
      <div className="kc-code-header">
        <span className="kc-code-lang">{lang || 'code'}</span>
        <button className="kc-code-copy" onClick={copy}>{copied ? '✓ copied' : '⧉ copy'}</button>
      </div>
      <pre className="kc-code-body"><code>{code}</code></pre>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatTs(ts) {
  if (!ts) return ''
  try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
  catch (_) { return '' }
}

// ─── Agent Approval Modal ─────────────────────────────────────────────────────
function AgentApprovalModal({ ctx, value, onChange, onSend, onQuickReply, onSkillApprove, onStop, onDismiss }) {
  const inputRef = useRef(null)
  const [showSuggest, setShowSuggest] = useState(false)
  const [approvalNote, setApprovalNote] = useState('')
  const [approvalBusy, setApprovalBusy] = useState('')
  const [approvalError, setApprovalError] = useState('')

  const approvalRequest = (ctx?.approvalRequest && typeof ctx.approvalRequest === 'object') ? ctx.approvalRequest : {}
  const approvalActions = (approvalRequest.actions && typeof approvalRequest.actions === 'object') ? approvalRequest.actions : {}
  const approvalMetadata = (approvalRequest.metadata && typeof approvalRequest.metadata === 'object') ? approvalRequest.metadata : {}
  const isSkillApproval = String(ctx?.kind || '').toLowerCase() === 'skill_approval'
    || String(approvalMetadata.approval_mode || '').toLowerCase() === 'skill_permission_grant'

  useEffect(() => {
    if (showSuggest) inputRef.current?.focus()
  }, [showSuggest])

  useEffect(() => {
    setApprovalNote('')
    setApprovalBusy('')
    setApprovalError('')
    setShowSuggest(false)
  }, [ctx?.runId, ctx?.scope, ctx?.kind])

  const handleKey = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); onSend() }
    if (e.key === 'Escape') onDismiss()
  }

  const handleSkillApproval = async (scope) => {
    if (!onSkillApprove) return
    setApprovalBusy(scope)
    setApprovalError('')
    try {
      await onSkillApprove(scope, approvalNote)
    } catch (err) {
      setApprovalError(err.message || 'Approval failed.')
    } finally {
      setApprovalBusy('')
    }
  }

  const suggestedScopes = Array.isArray(approvalMetadata.suggested_scopes) && approvalMetadata.suggested_scopes.length
    ? approvalMetadata.suggested_scopes
    : ['once', 'session', 'always']
  const scopeLabels = {
    once: 'Allow once',
    session: 'Allow this session',
    always: 'Always allow',
  }

  return (
    <div className="kc-modal-overlay" onClick={e => { if (!isSkillApproval && e.target === e.currentTarget) onDismiss() }}>
      <div className="kc-modal">
        <div className="kc-modal-header">
          <span className="kc-modal-icon">{isSkillApproval ? '🛡️' : '⏳'}</span>
          <span className="kc-modal-title">{approvalRequest.title || (isSkillApproval ? 'Skill permission required' : 'Agent is waiting for your input')}</span>
          {!isSkillApproval && <button className="kc-modal-close" onClick={onDismiss}>✕</button>}
        </div>
        {(approvalRequest.summary || ctx.prompt) && (
          <div className="kc-modal-prompt">
            <MarkdownRenderer content={approvalRequest.summary || ctx.prompt} />
          </div>
        )}
        {Array.isArray(approvalRequest.sections) && approvalRequest.sections.length > 0 && (
          <div className="kc-approval-sections">
            {approvalRequest.sections.map((section, index) => (
              <div key={`${section.title || 'section'}-${index}`} className="kc-approval-section">
                {section.title && <div className="kc-approval-section-title">{section.title}</div>}
                {Array.isArray(section.items) && section.items.length > 0 && (
                  <ul className="kc-approval-list">
                    {section.items.map((item, itemIndex) => (
                      <li key={`${index}-${itemIndex}`}>{item}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
        {approvalRequest.help_text && (
          <div className="kc-approval-help">{approvalRequest.help_text}</div>
        )}

        {isSkillApproval ? (
          <>
            <div className="kc-approval-note-row">
              <label className="kc-approval-label">Approval note</label>
              <textarea
                className="kc-modal-input"
                placeholder="Optional note for the audit log"
                value={approvalNote}
                onChange={e => setApprovalNote(e.target.value)}
                rows={2}
              />
            </div>
            {approvalError && <div className="kc-approval-error">⚠ {approvalError}</div>}
            <div className="kc-modal-quick kc-modal-quick--stacked">
              {suggestedScopes.map((scope) => (
                <button
                  key={scope}
                  className="kc-modal-quick-btn kc-modal-quick-btn--approve"
                  onClick={() => handleSkillApproval(scope)}
                  disabled={!!approvalBusy}
                >
                  {approvalBusy === scope ? 'Approving…' : (scopeLabels[scope] || `Approve (${scope})`)}
                </button>
              ))}
              <button className="kc-modal-quick-btn kc-modal-quick-btn--reject" onClick={onStop}>
                Stop run
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="kc-modal-quick">
              <button className="kc-modal-quick-btn kc-modal-quick-btn--approve" onClick={() => onQuickReply('approve')}>
                {approvalActions.accept_label || 'Approve'}
              </button>
              <button
                className={`kc-modal-quick-btn kc-modal-quick-btn--suggest${showSuggest ? ' kc-modal-quick-btn--active' : ''}`}
                onClick={() => { setShowSuggest(v => !v); onChange('') }}
              >
                {approvalActions.suggest_label || 'Suggest'}
              </button>
              <button className="kc-modal-quick-btn kc-modal-quick-btn--reject" onClick={() => onQuickReply('cancel')}>
                {approvalActions.reject_label || 'Reject'}
              </button>
            </div>
            {showSuggest && (
              <div className="kc-modal-input-row">
                <textarea
                  ref={inputRef}
                  className="kc-modal-input"
                  placeholder="Type your suggestion… (Ctrl+Enter to send)"
                  value={value}
                  onChange={e => onChange(e.target.value)}
                  onKeyDown={handleKey}
                  rows={3}
                />
                <button
                  className="kc-modal-send"
                  onClick={onSend}
                  disabled={!value.trim()}
                >
                  <SendIcon />
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function SendIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
}
function StopIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2.5"/></svg>
}
function ClearIcon() {
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
}
function HistoryIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
}
function ClockIcon({ size = 14 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
}

// ─── History List ─────────────────────────────────────────────────────────────
function HistoryList({ sessions, onLoad, onDelete }) {
  if (sessions.length === 0) {
    return <div className="kc-history-empty">No past conversations yet.<br/>Start a new chat and it will appear here.</div>
  }

  const now = Date.now()
  const todayStart     = new Date(new Date().setHours(0, 0, 0, 0)).getTime()
  const yesterdayStart = todayStart - 86400000
  const weekStart      = todayStart - 6 * 86400000

  const groups = { Today: [], Yesterday: [], 'Last 7 days': [], Older: [] }
  sessions.slice().reverse().forEach(s => {
    const ts = new Date(s.updatedAt || s.createdAt).getTime()
    if (ts >= todayStart)     groups['Today'].push(s)
    else if (ts >= yesterdayStart) groups['Yesterday'].push(s)
    else if (ts >= weekStart) groups['Last 7 days'].push(s)
    else                      groups['Older'].push(s)
  })

  return (
    <>
      {['Today', 'Yesterday', 'Last 7 days', 'Older'].map(label =>
        groups[label].length === 0 ? null : (
          <div key={label}>
            <div className="kc-history-group-label">{label}</div>
            {groups[label].map(s => (
              <div key={s.id} className="kc-history-item">
                <button className="kc-history-item-btn" onClick={() => onLoad(s)}>
                  <span className="kc-history-item-title">{s.title}</span>
                  <span className="kc-history-item-time">{formatRelTime(s.updatedAt || s.createdAt)}</span>
                </button>
                <button className="kc-history-item-del" title="Delete" onClick={e => { e.stopPropagation(); onDelete(s.id) }}>×</button>
              </div>
            ))}
          </div>
        )
      )}
    </>
  )
}
