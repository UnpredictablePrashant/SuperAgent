import React, { useState, useRef, useEffect, useCallback, useMemo, useReducer } from 'react'
import { useApp } from '../contexts/AppContext'
import GitDiffPreview from '../components/GitDiffPreview'
import { basename, resolveAgentCapability, resolveContextWindow, resolveSelectedModel } from '../lib/modelSelection'
import { buildActivityEntry, isPlanApprovalScope, isSkillApproval, shouldMirrorActivityMessage, summarizeRunArtifacts } from '../lib/runPresentation'

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

function logTimestampMs(value = '') {
  const raw = String(value || '').trim()
  if (!raw) return Number.NaN
  const direct = Date.parse(raw)
  if (Number.isFinite(direct)) return direct
  const normalized = raw.replace(' ', 'T').replace(',', '.')
  const parsed = Date.parse(normalized)
  return Number.isFinite(parsed) ? parsed : Number.NaN
}

function providerDisplayLabel(provider = '') {
  const normalized = String(provider || '').trim().toLowerCase()
  if (!normalized) return 'Model'
  if (normalized === 'ollama') return 'Local'
  if (normalized === 'xai') return 'xAI'
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function hasNativeWebSearchCapability(provider = '', model = '', capabilities = null) {
  if (capabilities && Object.prototype.hasOwnProperty.call(capabilities, 'native_web_search')) {
    return !!capabilities.native_web_search
  }
  const normalizedProvider = String(provider || '').trim().toLowerCase()
  if (normalizedProvider !== 'openai') return false
  const name = String(model || '').trim().toLowerCase()
  if (!name || name.includes('gpt-4.1-nano')) return false
  if (name.includes('deep-research')) return true
  return ['gpt-5', 'gpt-4o', 'gpt-4.1', 'o3', 'o4-'].some((needle) => name.includes(needle))
}

function synthesizeDeepResearchOption(rawValue, modelInventory) {
  const resolved = resolveSelectedModel(rawValue)
  if (!resolved.provider || !resolved.model) return null
  const capabilities = {
    native_web_search: hasNativeWebSearchCapability(resolved.provider, resolved.model),
  }
  return {
    value: `${resolved.provider}/${resolved.model}`,
    provider: resolved.provider,
    model: resolved.model,
    label: resolved.label,
    shortLabel: `${providerDisplayLabel(resolved.provider)} · ${resolved.model}`,
    isLocal: resolved.isLocal,
    ready: true,
    contextWindow: resolveContextWindow(rawValue, modelInventory),
    capabilities,
    note: '',
  }
}

function buildDeepResearchModelOptions(modelInventory, inheritedModel = '') {
  const providers = Array.isArray(modelInventory?.providers) ? modelInventory.providers : []
  const options = []
  const seen = new Set()
  for (const providerEntry of providers) {
    const provider = String(providerEntry?.provider || '').trim().toLowerCase()
    if (!provider) continue
    const ready = provider === 'ollama' ? !!providerEntry?.ready : providerEntry?.ready !== false
    const details = Array.isArray(providerEntry?.selectable_model_details) && providerEntry.selectable_model_details.length
      ? providerEntry.selectable_model_details
      : (String(providerEntry?.model || '').trim()
        ? [{
            name: String(providerEntry.model).trim(),
            context_window: Number(providerEntry?.context_window || 0),
            capabilities: providerEntry?.model_capabilities || {},
          }]
        : [])
    for (const detail of details) {
      const model = String(detail?.name || '').trim()
      if (!model) continue
      const value = `${provider}/${model}`
      if (seen.has(value)) continue
      seen.add(value)
      const detailCapabilities = (detail?.capabilities && typeof detail.capabilities === 'object')
        ? detail.capabilities
        : {}
      options.push({
        value,
        provider,
        model,
        label: `${providerDisplayLabel(provider)} · ${model}`,
        shortLabel: `${providerDisplayLabel(provider)} · ${model}`,
        isLocal: provider === 'ollama',
        ready,
        contextWindow: Number(detail?.context_window || providerEntry?.context_window || 0),
        capabilities: {
          ...detailCapabilities,
          native_web_search: hasNativeWebSearchCapability(provider, model, detailCapabilities),
        },
        note: String(providerEntry?.note || '').trim(),
      })
    }
  }
  const inheritedOption = synthesizeDeepResearchOption(inheritedModel, modelInventory)
  if (inheritedOption && !seen.has(inheritedOption.value)) options.unshift(inheritedOption)
  return options
}

function deepResearchModelDisabledReason(option, webSearchEnabled) {
  if (!option) return 'Choose a model.'
  if (!option.ready) {
    if (option.provider === 'ollama') return 'Local model runtime is not ready.'
    return option.note || `${providerDisplayLabel(option.provider)} is not configured.`
  }
  const modelName = String(option.model || '').trim().toLowerCase()
  if (modelName.includes('image-')) return 'Image-only models are not supported for report writing.'
  if (Number(option.contextWindow || 0) > 0 && Number(option.contextWindow || 0) < 32000) {
    return 'Context window is too small for long-form deep research.'
  }
  return ''
}

function scoreDeepResearchOption(option, { webSearchEnabled = true, preferredValue = '' } = {}) {
  if (!option) return Number.NEGATIVE_INFINITY
  let score = 0
  if (option.value === preferredValue) score += 1000
  if (!webSearchEnabled && option.isLocal) score += 240
  if (webSearchEnabled && option.provider === 'openai') score += 240
  if (webSearchEnabled && hasNativeWebSearchCapability(option.provider, option.model, option.capabilities)) score += 120
  const name = String(option.model || '').trim().toLowerCase()
  if (name.includes('gpt-5')) score += 160
  else if (name.includes('o3')) score += 145
  else if (name.includes('gpt-4.1')) score += 135
  else if (name.includes('gpt-4o')) score += 125
  else if (name.includes('claude')) score += 110
  else if (name.includes('gemini')) score += 100
  else if (name.includes('grok')) score += 95
  else if (name.includes('llama') || name.includes('qwen') || name.includes('mistral')) score += 80
  score += Math.min(Number(option.contextWindow || 0), 2_000_000) / 20_000
  return score
}

function resolveDeepResearchModelSelection({ requestedValue = '', inheritedValue = '', modelInventory = null, webSearchEnabled = true }) {
  const options = buildDeepResearchModelOptions(modelInventory, inheritedValue)
  const optionByValue = new Map(options.map((option) => [option.value, option]))
  const requestedOption = requestedValue
    ? (optionByValue.get(requestedValue) || synthesizeDeepResearchOption(requestedValue, modelInventory))
    : null
  const inheritedOption = inheritedValue
    ? (optionByValue.get(inheritedValue) || synthesizeDeepResearchOption(inheritedValue, modelInventory))
    : null
  const optionsWithState = options.map((option) => ({
    ...option,
    disabledReason: deepResearchModelDisabledReason(option, webSearchEnabled),
  }))
  const enabledOptions = optionsWithState.filter((option) => !option.disabledReason)
  const requestedReason = deepResearchModelDisabledReason(requestedOption, webSearchEnabled)
  const inheritedReason = deepResearchModelDisabledReason(inheritedOption, webSearchEnabled)
  const recommendedOption = enabledOptions.length
    ? [...enabledOptions].sort((left, right) => (
      scoreDeepResearchOption(right, { webSearchEnabled, preferredValue: inheritedValue })
      - scoreDeepResearchOption(left, { webSearchEnabled, preferredValue: inheritedValue })
    ))[0]
    : null
  const effectiveOption = requestedOption && !requestedReason
    ? requestedOption
    : inheritedOption && !inheritedReason
      ? inheritedOption
      : recommendedOption
  const effectiveSource = requestedOption && !requestedReason
    ? 'explicit'
    : inheritedOption && !inheritedReason
      ? 'header'
      : recommendedOption
        ? 'recommended'
        : 'none'
  return {
    options: optionsWithState,
    requestedOption,
    requestedReason,
    inheritedOption,
    inheritedReason,
    recommendedOption,
    effectiveOption,
    effectiveSource,
  }
}

// ─── Chat-local state ────────────────────────────────────────────────────────
const initChat = {
  messages: [],          // [{id,role,content,steps,status,runId,artifacts,progress,ts}]
  streaming: false,
  activeRunId: null,
  mode: 'chat',          // chat | plan | agent | research | security
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
          slot: String(a.item?.slot || '').trim(),
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
        const existingIndex = prev.findIndex((entry) => (
          String(entry?.id || '').trim() === item.id
          || (item.slot && String(entry?.slot || '').trim() === item.slot)
        ))
        if (existingIndex >= 0) {
          const existing = prev[existingIndex] || {}
          const nextItem = { ...existing, ...item, id: existing.id || item.id }
          if (
            String(existing.title || '') === nextItem.title
            && String(existing.detail || '') === nextItem.detail
            && String(existing.status || '') === nextItem.status
          ) return m
          const rest = prev.filter((_, idx) => idx !== existingIndex)
          return { ...m, progress: [nextItem, ...rest].slice(0, 14) }
        }
        const last = prev[0]
        if (last && last.title === item.title && last.detail === item.detail) return m
        const next = [item, ...prev].slice(0, 14)
        return { ...m, progress: next }
      })
      return { ...s, messages: msgs }
    }
    case 'ADD_LOG_ENTRY': {
      const msgs = s.messages.map(m => {
        if (m.id !== a.msgId) return m
        const item = {
          id: String(a.item?.id || `l-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
          ts: String(a.item?.ts || a.item?.timestamp || new Date().toISOString()).trim(),
          clock: String(a.item?.clock || '').trim(),
          text: String(a.item?.text || '').trim(),
          category: String(a.item?.category || 'info').trim(),
        }
        if (!item.text) return m
        const prev = Array.isArray(m.logs) ? m.logs : []
        if (prev.some((entry) => entry && entry.text === item.text && entry.ts === item.ts)) return m
        const next = [...prev, item]
          .sort((left, right) => {
            const leftMs = logTimestampMs(left?.ts || left?.timestamp || '')
            const rightMs = logTimestampMs(right?.ts || right?.timestamp || '')
            if (Number.isFinite(leftMs) && Number.isFinite(rightMs) && leftMs !== rightMs) return leftMs - rightMs
            if (Number.isFinite(leftMs) !== Number.isFinite(rightMs)) return Number.isFinite(leftMs) ? -1 : 1
            return String(left?.ts || left?.timestamp || '').localeCompare(String(right?.ts || right?.timestamp || ''))
          })
          .slice(-40)
        return { ...m, logs: next }
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
    : mode === 'plan'
      ? `Use planning mode. Create a concrete execution plan first, keep it concise, ask for approval before implementation, and wait for the user before making changes.\n\nUser request: ${text}`
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
  if (mode === 'agent' || mode === 'plan') {
    return {
      ...base,
      local_drive_paths: localPaths.length ? localPaths : undefined,
      local_drive_recursive: localPaths.length ? true : undefined,
      execution_mode: mode === 'plan' ? 'plan' : undefined,
      planner_mode: mode === 'plan' ? 'always' : undefined,
      auto_approve_plan: mode === 'plan' ? false : undefined,
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
  const webLinks = links

  // Compute research_sources: checked remote + 'local' if paths present
  const remoteSources = dr.webSearchEnabled ? dr.sources : []
  const mergedLocalPaths = Array.from(new Set([...(dr.localPaths || []), ...localPaths]))
  const allSources = mergedLocalPaths.length
    ? Array.from(new Set([...remoteSources, 'local']))
    : remoteSources
  const depthPreset = resolveDeepResearchDepthPreset(dr.depthMode, dr.pages)

  const payload = {
    ...base,
    deep_research_mode:              true,
    long_document_mode:              true,
    workflow_type:                   'deep_research',
    long_document_pages:             depthPreset.pages,
    research_depth_mode:             depthPreset.id,
    research_output_formats:         dr.outputFormats,
    research_citation_style:         dr.citationStyle,
    research_enable_plagiarism_check: dr.plagiarismCheck,
    research_web_search_enabled:     dr.webSearchEnabled,
    research_date_range:             dr.dateRange,
    research_sources:                allSources,
    research_max_sources:            dr.maxSources || 0,
    research_checkpoint_enabled:     dr.checkpointing,
    research_kb_enabled:             !!dr.kbEnabled,
    research_kb_id:                  dr.kbEnabled ? (dr.kbId || '') : '',
    research_kb_top_k:               dr.kbTopK || 8,
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
  if (mode === 'plan') return 'Plan'
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

function shouldInlineAwaitingContext(ctx) {
  if (!ctx || typeof ctx !== 'object') return false
  return hasConcreteAwaitingContext(ctx) && !isSkillApproval(ctx.kind, ctx.approvalRequest)
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

function summarizeLogFeed(logs = []) {
  const items = Array.isArray(logs) ? logs : []
  if (!items.length) return 'Waiting for execution log output...'
  const latest = String(items[items.length - 1]?.text || '').trim()
  if (!latest) return `${items.length} log update${items.length === 1 ? '' : 's'} captured`
  const clipped = latest.length > 120 ? `${latest.slice(0, 117)}...` : latest
  return `${items.length} log update${items.length === 1 ? '' : 's'} captured. Latest: ${clipped}`
}

const GENERIC_PROGRESS_TITLES = new Set(['runtime update', 'activity'])

function normalizeLiveProgressItem(item = null) {
  const safe = item && typeof item === 'object' ? item : {}
  const rawTitle = String(safe.title || '').trim()
  const rawDetail = String(safe.detail || '').trim()
  const genericTitle = GENERIC_PROGRESS_TITLES.has(rawTitle.toLowerCase())
  const title = genericTitle && rawDetail ? rawDetail : (rawTitle || rawDetail)
  const detail = genericTitle && rawDetail ? '' : (rawDetail && rawDetail !== title ? rawDetail : '')
  return {
    ...safe,
    title,
    detail,
    kind: String(safe.kind || 'activity').trim().toLowerCase(),
    status: String(safe.status || 'running').trim().toLowerCase(),
    actor: String(safe.actor || '').trim(),
    durationLabel: String(safe.durationLabel || '').trim(),
    cwd: String(safe.cwd || '').trim(),
    command: String(safe.command || '').trim(),
  }
}

function buildLiveProgressItem(progress = [], statusText = '', fallbackStatus = '') {
  const items = Array.isArray(progress) ? progress : []
  for (const item of items) {
    const normalized = normalizeLiveProgressItem(item)
    if (normalized.title) return normalized
  }
  const detail = sanitizeStatusMessage(statusText)
  if (!detail) return null
  return {
    id: 'runtime-status-fallback',
    slot: 'runtime-status',
    title: detail,
    detail: '',
    kind: 'status',
    status: String(fallbackStatus || 'running').trim().toLowerCase(),
    actor: '',
    durationLabel: '',
    cwd: '',
    command: '',
  }
}

function liveProgressLabel(item = null) {
  const kind = String(item?.kind || '').trim().toLowerCase()
  if (kind === 'status') return 'Runtime'
  if (kind === 'step') return 'Current Step'
  if (kind === 'intent') return 'Research Intent'
  if (kind === 'source_strategy') return 'Source Strategy'
  if (kind === 'coverage') return 'Coverage'
  if (kind === 'artifact_created') return 'Artifacts'
  if (kind === 'quality_gate') return 'Quality Check'
  if (kind === 'gap_detected') return 'Gap Review'
  return 'Current Step'
}

function isPendingRunStatus(status) {
  return ['thinking', 'streaming', 'awaiting'].includes(String(status || '').trim().toLowerCase())
}

function isStreamingRunStatus(status) {
  return ['thinking', 'streaming'].includes(String(status || '').trim().toLowerCase())
}

function failureMessageForRecoveredRun(runId, status = '') {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'failed') return `Run ${runId} failed while the app was offline.`
  if (normalized === 'cancelled') return `Run ${runId} was cancelled while the app was offline.`
  return `Run ${runId} could not be recovered after the app restarted.`
}

const EXECUTION_LOG_LINE_RE = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - ([A-Z]+) - (.*)$/

function executionLogClockLabel(value = '') {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const match = raw.match(/\b(\d{2}:\d{2}:\d{2})\b/)
  return match ? match[1] : raw
}

function compactExecutionLogText(value, limit = 220) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (!text) return ''
  return text.length > limit ? `${text.slice(0, limit - 3).trimEnd()}...` : text
}

function executionLogDisplayName(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.replace(/_agent$/i, '').replace(/_/g, ' ').trim()
}

function executionLogBasename(value) {
  const text = String(value || '').trim().replace(/^["']|["']$/g, '')
  if (!text) return ''
  const normalized = text.replace(/\\/g, '/').replace(/\/+$/, '')
  const idx = normalized.lastIndexOf('/')
  return idx >= 0 ? normalized.slice(idx + 1) : normalized
}

function summarizeExecutionLogMessage(message) {
  const raw = String(message || '').trim()
  if (!raw || raw === '[LLM Prompt]') return null
  if (raw.startsWith('[LLM Call]')) {
    const agent = raw.match(/agent=([^|]+)/i)?.[1]?.trim()
    const model = raw.match(/model=([^|]+)/i)?.[1]?.trim()
    const promptChars = raw.match(/prompt_chars=(\d+)/i)?.[1]?.trim()
    const parts = ['LLM call']
    if (agent) parts.push(executionLogDisplayName(agent))
    if (model) parts.push(model)
    if (promptChars) parts.push(`${Number(promptChars).toLocaleString()} prompt chars`)
    return { text: parts.filter(Boolean).join(' · '), category: 'llm_call' }
  }
  if (raw.startsWith('[LLM OK]')) {
    const agent = raw.match(/agent=([^|]+)/i)?.[1]?.trim()
    const model = raw.match(/model=([^|]+)/i)?.[1]?.trim()
    const elapsed = raw.match(/elapsed_ms=(\d+)/i)?.[1]?.trim()
    const parts = ['LLM response']
    if (agent) parts.push(executionLogDisplayName(agent))
    if (model) parts.push(model)
    if (elapsed) parts.push(`${Math.round(Number(elapsed))} ms`)
    return { text: parts.filter(Boolean).join(' · '), category: 'llm_ok' }
  }
  if (raw.startsWith('[files] wrote:')) {
    const path = raw.split(':').slice(1).join(':').trim()
    return {
      text: `Wrote artifact · ${executionLogBasename(path) || compactExecutionLogText(path)}`,
      category: 'artifact',
    }
  }
  return {
    text: compactExecutionLogText(raw.replace(/^\[([^\]]+)\]\s*/, '$1 · ')),
    category: 'info',
  }
}

function summarizeExecutionLogContinuation(line) {
  const raw = String(line || '').trim()
  if (!raw) return null
  if (/^[A-Za-z]:[\\/]/.test(raw) || raw.startsWith('/')) {
    const name = executionLogBasename(raw)
    return name ? { text: `File · ${name}`, category: 'file' } : null
  }
  if (/^characters:/i.test(raw)) {
    return { text: compactExecutionLogText(raw, 120), category: 'meta' }
  }
  if (/^reason:/i.test(raw)) {
    return { text: `Reason · ${compactExecutionLogText(raw.replace(/^reason:/i, ''), 160)}`, category: 'meta' }
  }
  return null
}

function parseExecutionLogLine(line, state = {}) {
  const raw = String(line || '').replace(/\r?\n$/, '')
  if (!raw.trim()) return null
  const match = raw.match(EXECUTION_LOG_LINE_RE)
  if (match) {
    state.skipMultiline = false
    state.lastTimestamp = match[1]
    const message = String(match[3] || '').trim()
    if (message === '[LLM Prompt]') {
      state.skipMultiline = true
      return null
    }
    const summary = summarizeExecutionLogMessage(message)
    if (!summary?.text) return null
    return {
      ts: state.lastTimestamp || '',
      clock: executionLogClockLabel(state.lastTimestamp || ''),
      text: summary.text,
      category: summary.category || 'info',
    }
  }
  if (state.skipMultiline) return null
  const summary = summarizeExecutionLogContinuation(raw)
  if (!summary?.text) return null
  return {
    ts: String(state.lastTimestamp || '').trim(),
    clock: executionLogClockLabel(state.lastTimestamp || ''),
    text: summary.text,
    category: summary.category || 'info',
  }
}

function buildExecutionLogSignature(item = {}) {
  return `${String(item.ts || item.timestamp || '').trim()}|${String(item.text || '').trim()}`
}

const GENERIC_AWAITING_TEXTS = new Set([
  'waiting for your input',
  'waiting for your input.',
  'need clarification',
  'need confirmation',
  'approval required',
  'permission required',
  'plan approval needed',
  'run paused for your input. reply here to continue the same workflow.',
  'kendr paused this run, but the backend did not provide the exact question. review the latest execution log and reply with what should happen next.',
  'waiting for your reply above...',
  'waiting for execution log output...',
])

function normalizeAwaitingText(value = '') {
  return String(value || '')
    .replace(/\u2026/g, '...')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

function isMeaningfulAwaitingText(value = '') {
  const normalized = normalizeAwaitingText(value)
  return !!normalized && !GENERIC_AWAITING_TEXTS.has(normalized)
}

function sectionHasMeaningfulAwaitingText(section = {}) {
  if (!section || typeof section !== 'object') return false
  if (isMeaningfulAwaitingText(section.title)) return true
  const items = Array.isArray(section.items) ? section.items : []
  return items.some((item) => {
    if (typeof item === 'string') return isMeaningfulAwaitingText(item)
    if (!item || typeof item !== 'object') return false
    return (
      isMeaningfulAwaitingText(item.title)
      || isMeaningfulAwaitingText(item.text)
      || isMeaningfulAwaitingText(item.label)
      || isMeaningfulAwaitingText(item.value)
    )
  })
}

function hasConcreteAwaitingRequest(request = null) {
  const safe = request && typeof request === 'object' ? request : {}
  const sections = Array.isArray(safe.sections) ? safe.sections : []
  return !!(
    isMeaningfulAwaitingText(safe.summary)
    || isMeaningfulAwaitingText(safe.title)
    || isMeaningfulAwaitingText(safe.help_text)
    || sections.some(sectionHasMeaningfulAwaitingText)
  )
}

const ACTIVE_RUN_STATUSES = new Set(['running', 'started', 'cancelling'])
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled'])

function runSnapshotResult(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  return data.result && typeof data.result === 'object' ? data.result : {}
}

function runSnapshotStatus(snapshot, fallbackStatus = '') {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = runSnapshotResult(data)
  return String(data.status || result.status || fallbackStatus || '').trim().toLowerCase()
}

function runSnapshotApprovalRequest(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = runSnapshotResult(data)
  return result.approval_request && typeof result.approval_request === 'object'
    ? result.approval_request
    : (data.approval_request && typeof data.approval_request === 'object' ? data.approval_request : {})
}

function runSnapshotSignalsAwaiting(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = runSnapshotResult(data)
  const status = runSnapshotStatus(data)
  if (ACTIVE_RUN_STATUSES.has(status) || TERMINAL_RUN_STATUSES.has(status)) return false
  return !!(
    status === 'awaiting_user_input'
    || result.awaiting_user_input
    || data.awaiting_user_input
    || result.plan_waiting_for_approval
    || result.plan_needs_clarification
    || result.pending_user_input_kind
    || data.pending_user_input_kind
    || result.approval_pending_scope
    || data.approval_pending_scope
    || result.pending_user_question
    || data.pending_user_question
    || Object.keys(runSnapshotApprovalRequest(data)).length > 0
  )
}

function runSnapshotAwaitingPrompt(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = runSnapshotResult(data)
  return String(result.pending_user_question || data.pending_user_question || '').trim()
}

function runSnapshotAwaitingScope(snapshot, fallbackScope = '') {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = runSnapshotResult(data)
  return String(result.approval_pending_scope || data.approval_pending_scope || fallbackScope || '').trim()
}

function runSnapshotAwaitingKind(snapshot, fallbackKind = '') {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = runSnapshotResult(data)
  return String(result.pending_user_input_kind || data.pending_user_input_kind || fallbackKind || '').trim()
}

function normalizeAwaitingRequest(request = null, prompt = '', scope = '', kind = '') {
  const safe = request && typeof request === 'object' ? request : {}
  const sections = Array.isArray(safe.sections) ? safe.sections.filter(sectionHasMeaningfulAwaitingText) : []
  const actions = (safe.actions && typeof safe.actions === 'object') ? safe.actions : {}
  const summary = String(safe.summary || prompt || '').trim()
  const helpText = String(safe.help_text || '').trim()
  const explicitTitle = String(safe.title || '').trim()
  const derivedTitle = explicitTitle || awaitingTitleFromContext(scope, kind, safe)
  const normalized = {
    ...safe,
    actions,
  }
  if (summary) normalized.summary = summary
  else delete normalized.summary
  if (helpText) normalized.help_text = helpText
  else delete normalized.help_text
  if (explicitTitle) normalized.title = explicitTitle
  else if (
    isMeaningfulAwaitingText(derivedTitle)
    && (summary || helpText || sections.length || hasExplicitAwaitingActions(safe))
  ) normalized.title = derivedTitle
  else delete normalized.title
  if (sections.length) normalized.sections = sections
  else delete normalized.sections
  return normalized
}

function resolveRunSnapshotLogPath(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const logPaths = data.log_paths && typeof data.log_paths === 'object' ? data.log_paths : {}
  const direct = String(logPaths.execution_log || '').trim()
  if (direct) return direct
  const runDir = String(data.run_output_dir || data.output_dir || data.resume_output_dir || '').trim()
  if (!runDir) return ''
  const normalized = runDir.replace(/[\\/]+$/, '')
  const separator = normalized.includes('\\') ? '\\' : '/'
  return `${normalized}${separator}execution.log`
}

function runSnapshotOutputText(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = data.result && typeof data.result === 'object' ? data.result : {}
  return String(
    result.final_output || result.output || result.draft_response || result.response
    || data.final_output || data.output || data.response || '',
  ).trim()
}

function runSnapshotErrorText(snapshot, runId, fallbackStatus = '') {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = runSnapshotResult(data)
  const status = runSnapshotStatus(data, fallbackStatus)
  const detail = String(
    data.last_error || result.last_error || data.error || result.error || runSnapshotOutputText(snapshot),
  ).trim()
  if (detail) return detail
  if (status === 'failed' || status === 'cancelled') return failureMessageForRecoveredRun(runId, status)
  return ''
}

function runSnapshotArtifacts(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = data.result && typeof data.result === 'object' ? data.result : {}
  return result.artifact_files || data.artifact_files || []
}

function runSnapshotChecklist(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = data.result && typeof data.result === 'object' ? data.result : {}
  return extractChecklist(Object.keys(result).length ? result : data)
}

function runSnapshotMessageMeta(snapshot) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const status = runSnapshotStatus(data)
  const logPath = resolveRunSnapshotLogPath(data)
  return {
    runStartedAt: data.started_at || data.created_at || '',
    runOutputDir: String(data.run_output_dir || data.output_dir || data.resume_output_dir || '').trim(),
    executionLogPath: logPath,
    lastKnownRunStatus: status,
    lastError: runSnapshotErrorText(data, String(data.run_id || '').trim(), status),
  }
}

function approvalScopeLabel(scope = '') {
  return String(scope || '').trim().replace(/[_-]+/g, ' ')
}

function awaitingTitleFromContext(scope = '', kind = '', request = null) {
  const explicit = String(request?.title || '').trim()
  if (explicit) return explicit
  const scopeText = String(scope || '').trim().toLowerCase()
  const kindText = String(kind || '').trim().toLowerCase()
  if (kindText.includes('clar') || scopeText.includes('clar')) return 'Need clarification'
  if (kindText.includes('confirm') || scopeText.includes('confirm')) return 'Need confirmation'
  if (kindText.includes('approval') || scopeText.includes('approval')) return 'Approval required'
  if (kindText.includes('permission') || scopeText.includes('permission')) return 'Permission required'
  if (scopeText.includes('plan')) return 'Plan approval needed'
  return 'Waiting for your input'
}

function hasExplicitAwaitingActions(request = null) {
  const actions = (request && typeof request === 'object' && request.actions && typeof request.actions === 'object')
    ? request.actions
    : {}
  return !!(
    String(actions.accept_label || '').trim()
    || String(actions.reject_label || '').trim()
    || String(actions.suggest_label || '').trim()
  )
}

function isApprovalLikeAwaiting(scope = '', kind = '', request = null) {
  if (hasExplicitAwaitingActions(request)) return true
  const scopeText = String(scope || '').trim().toLowerCase()
  const kindText = String(kind || '').trim().toLowerCase()
  return (
    scopeText.includes('approval')
    || scopeText.includes('permission')
    || scopeText.includes('plan')
    || kindText.includes('approval')
    || kindText.includes('permission')
    || kindText.includes('confirm')
  )
}

function buildAwaitingState(snapshot, fallback = {}) {
  if (!runSnapshotSignalsAwaiting(snapshot)) return null
  const prompt = runSnapshotAwaitingPrompt(snapshot)
  const scope = runSnapshotAwaitingScope(snapshot, fallback?.approvalScope || '')
  const kind = runSnapshotAwaitingKind(snapshot, fallback?.approvalKind || '')
  const normalizedRequest = normalizeAwaitingRequest(runSnapshotApprovalRequest(snapshot), prompt, scope, kind)
  const summary = String(normalizedRequest.summary || prompt || '').trim()
  const helpText = String(normalizedRequest.help_text || '').trim()
  const title = String(normalizedRequest.title || '').trim()
  if (!isMeaningfulAwaitingText(prompt) && !hasConcreteAwaitingRequest(normalizedRequest)) return null
  return {
    content: summary,
    status: 'awaiting',
    statusText: summary || helpText || title || 'Waiting for your input.',
    approvalScope: scope,
    approvalKind: kind,
    approvalRequest: normalizedRequest,
    approvalState: 'pending',
    awaitingDecision: isApprovalLikeAwaiting(scope, kind, normalizedRequest) ? 'approval' : 'reply',
  }
}

function hasConcreteAwaitingPrompt(snapshot) {
  return !!buildAwaitingState(snapshot)
}

function buildAwaitingContext(snapshot, runId, messageId, awaitingState = null) {
  const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
  const result = runSnapshotResult(data)
  const awaiting = awaitingState || buildAwaitingState(data)
  if (!awaiting) return null
  return {
    runId,
    workflowId: String(data.workflow_id || result.workflow_id || runId),
    messageId,
    prompt: awaiting.content || awaiting.statusText || '',
    kind: awaiting.approvalKind || '',
    scope: awaiting.approvalScope || '',
    approvalRequest: awaiting.approvalRequest || null,
  }
}

function invalidAwaitingMessage(snapshot, runId, fallback = {}) {
  const latestLog = String((Array.isArray(fallback?.logs) ? fallback.logs[0]?.text : '') || '').trim()
  const scope = approvalScopeLabel(
    snapshot?.result?.approval_pending_scope
    || snapshot?.approval_pending_scope
    || fallback?.approvalScope
    || '',
  )
  const parts = [`Run ${runId} paused without asking a concrete question.`]
  if (scope) parts.push(`Reported scope: ${scope}.`)
  if (latestLog) parts.push(`Latest log: ${latestLog}`)
  else {
    const detail = runSnapshotErrorText(snapshot, runId, String(snapshot?.status || snapshot?.result?.status || ''))
    if (detail) parts.push(detail)
  }
  return parts.join(' ')
}

function messageHasConcreteAwaitingPrompt(msg) {
  const approvalRequest = (msg?.approvalRequest && typeof msg.approvalRequest === 'object') ? msg.approvalRequest : {}
  return !!(
    isMeaningfulAwaitingText(msg?.content || '')
    || hasConcreteAwaitingRequest(approvalRequest)
  )
}

function hasConcreteAwaitingContext(ctx) {
  if (!ctx || typeof ctx !== 'object') return false
  return (
    isMeaningfulAwaitingText(ctx.prompt)
    || hasConcreteAwaitingRequest(ctx.approvalRequest)
  )
}

function hasDisplayableAwaitingContext(ctx) {
  if (!ctx || typeof ctx !== 'object') return false
  return isSkillApproval(ctx.kind, ctx.approvalRequest) || hasConcreteAwaitingContext(ctx)
}

function clearAwaitingMessageFields(patch = {}) {
  return {
    ...patch,
    approvalScope: '',
    approvalKind: '',
    approvalRequest: null,
    awaitingDecision: '',
    approvalState: '',
  }
}

function buildRunningMessagePatch(snapshot, fallback = {}) {
  const latestLog = String((Array.isArray(fallback?.logs) ? fallback.logs[0]?.text : '') || '').trim()
  const fallbackWasAwaiting = String(fallback?.status || '').trim().toLowerCase() === 'awaiting'
  const fallbackStatusText = (!fallbackWasAwaiting && isMeaningfulAwaitingText(fallback?.statusText)) ? String(fallback.statusText).trim() : ''
  const fallbackContent = (!fallbackWasAwaiting && isMeaningfulAwaitingText(fallback?.content)) ? String(fallback.content).trim() : ''
  return clearAwaitingMessageFields({
    ...runSnapshotMessageMeta(snapshot),
    content: fallbackContent,
    status: 'streaming',
    statusText: isMeaningfulAwaitingText(latestLog) ? latestLog : fallbackStatusText,
  })
}

function buildCompletedMessagePatch(snapshot, fallback = {}) {
  const fallbackWasAwaiting = String(fallback?.status || '').trim().toLowerCase() === 'awaiting'
  return clearAwaitingMessageFields({
    ...runSnapshotMessageMeta(snapshot),
    content: runSnapshotOutputText(snapshot) || (fallbackWasAwaiting ? '' : String(fallback?.content || '').trim()),
    status: 'done',
    statusText: '',
    artifacts: runSnapshotArtifacts(snapshot),
    checklist: runSnapshotChecklist(snapshot),
  })
}

function buildFailedMessagePatch(snapshot, runId, fallbackStatus = '', fallback = {}) {
  return clearAwaitingMessageFields({
    ...runSnapshotMessageMeta(snapshot),
    content: runSnapshotErrorText(snapshot, runId, fallbackStatus) || invalidAwaitingMessage(snapshot, runId, fallback),
    status: 'error',
    statusText: '',
    artifacts: runSnapshotArtifacts(snapshot),
    checklist: runSnapshotChecklist(snapshot),
  })
}

function buildInvalidAwaitingErrorPatch(snapshot, runId, fallback = {}) {
  return clearAwaitingMessageFields({
    ...runSnapshotMessageMeta(snapshot),
    content: invalidAwaitingMessage(snapshot, runId, fallback),
    status: 'error',
    statusText: '',
    artifacts: runSnapshotArtifacts(snapshot),
    checklist: runSnapshotChecklist(snapshot),
  })
}

function buildInvalidAwaitingRunningPatch(snapshot, fallback = {}, statusText = 'Run sent an invalid pause signal. Rechecking backend status...') {
  return {
    ...buildRunningMessagePatch(snapshot, fallback),
    statusText,
    artifacts: runSnapshotArtifacts(snapshot),
    checklist: runSnapshotChecklist(snapshot),
  }
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
  depthMode: 'standard',
  pages: 25,
  researchModel: '',
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
  kbEnabled: false,
  kbId: '',
  kbTopK: 8,
  collapsed: false,
}

const DEEP_RESEARCH_DEPTH_PRESETS = [
  {
    id: 'brief',
    pages: 10,
    label: 'Focused Brief',
    summary: 'Focused',
    hint: 'Fastest run for a narrower scope and the most important findings.',
  },
  {
    id: 'standard',
    pages: 25,
    label: 'Standard Report',
    summary: 'Standard',
    hint: 'Balanced depth for most multi-section research tasks.',
  },
  {
    id: 'comprehensive',
    pages: 50,
    label: 'Comprehensive Study',
    summary: 'Comprehensive',
    hint: 'Broader source sweep and deeper synthesis across sections.',
  },
  {
    id: 'exhaustive',
    pages: 100,
    label: 'Exhaustive Dossier',
    summary: 'Exhaustive',
    hint: 'Maximum breadth and depth; slower and more resource-intensive.',
  },
]

function normalizeDeepResearchDepthMode(value, pages) {
  const normalized = String(value || '').trim().toLowerCase()
  if (DEEP_RESEARCH_DEPTH_PRESETS.some((item) => item.id === normalized)) return normalized
  const numericPages = Number(pages || 0)
  if (numericPages >= 100) return 'exhaustive'
  if (numericPages >= 50) return 'comprehensive'
  if (numericPages >= 20) return 'standard'
  return 'brief'
}

function resolveDeepResearchDepthPreset(value, pages) {
  const mode = normalizeDeepResearchDepthMode(value, pages)
  return DEEP_RESEARCH_DEPTH_PRESETS.find((item) => item.id === mode) || DEEP_RESEARCH_DEPTH_PRESETS[1]
}

// ─── Component ───────────────────────────────────────────────────────────────
export default function ChatPanel({ fullWidth = false, hideHeader = false, studioMode = false, minimalStudio = false, studioAccessory = null }) {
  const { state: appState, dispatch: appDispatch, openFile, refreshModelInventory } = useApp()
  const api = window.kendrAPI
  const [chat, dispatch] = useReducer(chatReducer, undefined, () => ({ ...initChat, messages: loadHistory() }))
  const [input, setInput] = useState('')
  const [resumeInput, setResumeInput] = useState('')
  const [chatId, setChatId] = useState(() => `chat-${Date.now()}`)
  const [dr, setDr] = useState(DR_DEFAULTS)
  const [attachments, setAttachments] = useState([])
  const [researchKbs, setResearchKbs] = useState([])
  const [mcpEnabled, setMcpEnabled] = useState(false)
  const [mcpServerCount, setMcpServerCount] = useState(0)
  const [mcpUndiscovered, setMcpUndiscovered] = useState(0)
  const [machineStatus, setMachineStatus] = useState(null)
  const [machineStatusLoaded, setMachineStatusLoaded] = useState(false)
  const [machineSyncRunning, setMachineSyncRunning] = useState(false)
  const [diffPreviewPath, setDiffPreviewPath] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const [sessions, setSessions] = useState(() => loadSessions())
  const [composerMenuOpen, setComposerMenuOpen] = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const composerMenuRef = useRef(null)
  const esRef = useRef(null)
  const resumeAttemptedRunRef = useRef('')
  const staleRunRecoveryRef = useRef('')
  const mirroredActivityIdsRef = useRef([])
  const apiBase = appState.backendUrl || 'http://127.0.0.1:2151'
  const updateDr = (patch) => setDr(s => ({ ...s, ...patch }))
  const deepResearchDepthPreset = resolveDeepResearchDepthPreset(dr.depthMode, dr.pages)
  const selectedModelMeta = resolveSelectedModel(appState.selectedModel)
  const isSimpleStudioChat = studioMode && chat.mode === 'chat'
  const modelInventory = appState.modelInventory
  const deepResearchModelState = useMemo(() => resolveDeepResearchModelSelection({
    requestedValue: dr.researchModel,
    inheritedValue: appState.selectedModel || '',
    modelInventory,
    webSearchEnabled: !!dr.webSearchEnabled,
  }), [dr.researchModel, dr.webSearchEnabled, appState.selectedModel, modelInventory])
  const effectiveDeepResearchModel = deepResearchModelState.effectiveOption
  const composerModelRaw = chat.mode === 'research'
    ? (effectiveDeepResearchModel?.value || appState.selectedModel || '')
    : (appState.selectedModel || '')
  const composerModelMeta = resolveSelectedModel(composerModelRaw)
  const selectedModelAgentCapable = resolveAgentCapability(appState.selectedModel, modelInventory)
  const contextLimit = resolveContextWindow(composerModelRaw, modelInventory)
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
    const activePayloadModel = chat.mode === 'research'
      ? effectiveDeepResearchModel
      : (appState.selectedModel ? resolveSelectedModel(appState.selectedModel) : null)
    if (activePayloadModel) {
      const selected = activePayloadModel
      if (selected.provider) body.provider = selected.provider
      if (selected.model) body.model = selected.model
    }
    if (chat.mode === 'research' && effectiveDeepResearchModel?.model) {
      body.research_model = effectiveDeepResearchModel.model
    }
    body.context_limit = contextLimit
    if (isSimpleStudioChat) body.stream = true
    return body
  }, [input, chatId, appState.projectRoot, chat.mode, dr, attachments, studioMode, mcpEnabled, chat.messages, appState.selectedModel, isSimpleStudioChat, contextLimit, effectiveDeepResearchModel])
  const estimatedContextTokens = estimateObjectTokens(payloadPreview)
  const contextPct = Math.min(100, Math.round((estimatedContextTokens / Math.max(contextLimit, 1)) * 100))
  const stickyChecklistMsg = useMemo(() => latestChecklistMessage(chat.messages), [chat.messages])
  const stickyChecklist = Array.isArray(stickyChecklistMsg?.checklist) ? stickyChecklistMsg.checklist : []
  const latestStreamingRunMsg = useMemo(() => (
    [...(chat.messages || [])].reverse().find((msg) => (
      msg?.role === 'assistant'
      && String(msg?.runId || '').trim()
      && isStreamingRunStatus(msg?.status)
    )) || null
  ), [chat.messages])
  const activeRunId = String(chat.activeRunId || appState.activeRunId || latestStreamingRunMsg?.runId || '').trim()
  const awaitingRunId = String(chat.awaitingContext?.runId || '').trim()
  const stopTargetRunId = activeRunId || awaitingRunId
  const composerRunActive = !chat.awaitingContext && !!activeRunId
  const inlineAwaiting = shouldInlineAwaitingContext(chat.awaitingContext)
  const displayableAwaitingContext = hasDisplayableAwaitingContext(chat.awaitingContext)
  const hasMessages = chat.messages.length > 0
  const showInlineAttachmentTools = !minimalStudio
  const showInlineContextTools = !minimalStudio
  const showInlineFlowStrip = !minimalStudio
  const indexedResearchKbs = useMemo(
    () => (Array.isArray(researchKbs) ? researchKbs.filter(kb => String(kb?.status || '').trim().toLowerCase() === 'indexed') : []),
    [researchKbs],
  )
  const activeResearchKb = useMemo(
    () => (Array.isArray(researchKbs) ? researchKbs.find(kb => !!kb?.is_active) || null : null),
    [researchKbs],
  )
  const selectedResearchKb = useMemo(() => {
    if (!dr.kbEnabled) return null
    if (dr.kbId) return indexedResearchKbs.find(kb => kb.id === dr.kbId) || null
    return activeResearchKb
  }, [dr.kbEnabled, dr.kbId, indexedResearchKbs, activeResearchKb])

  useEffect(() => {
    if (!dr.researchModel) return
    if (!deepResearchModelState.requestedReason) return
    setDr((current) => (
      current.researchModel === dr.researchModel
        ? { ...current, researchModel: '' }
        : current
    ))
  }, [dr.researchModel, deepResearchModelState.requestedReason])

  const loadResearchKbs = useCallback(async () => {
    try {
      const resp = await fetch(`${apiBase}/api/rag/kbs`)
      const data = await resp.json().catch(() => [])
      const next = Array.isArray(data) ? data : []
      setResearchKbs(next)
      return next
    } catch (_) {
      setResearchKbs([])
      return []
    }
  }, [apiBase])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      try {
        const resp = await fetch(`${apiBase}/api/rag/kbs`)
        const data = await resp.json().catch(() => [])
        if (!cancelled) setResearchKbs(Array.isArray(data) ? data : [])
      } catch (_) {
        if (!cancelled) setResearchKbs([])
      }
    }
    run()
    return () => { cancelled = true }
  }, [apiBase])
  const planKeywordsDetected = /\b(plan|roadmap|outline|steps|milestones|strategy)\b/i.test(input)
  const showPlanSuggestion = minimalStudio && selectedModelAgentCapable && !composerRunActive && chat.mode === 'chat' && planKeywordsDetected
  const showActiveWorkflowChip = minimalStudio && chat.mode !== 'chat'
  const resolveArtifactActionUrl = useCallback((item, runId, action = 'download') => {
    const direct = String(
      action === 'view'
        ? (item?.viewUrl || item?.view_url || '')
        : (item?.downloadUrl || item?.download_url || ''),
    ).trim()
    if (direct) {
      try {
        return new URL(direct, apiBase || window.location.origin).toString()
      } catch (_) {
        return direct
      }
    }
    const resolvedRunId = String(runId || '').trim()
    const artifactName = String(item?.name || item?.label || basename(item?.path || '')).trim()
    if (!resolvedRunId || !artifactName) return ''
    const base = String(apiBase || '').replace(/\/$/, '')
    return `${base}/api/artifacts/${action}?run_id=${encodeURIComponent(resolvedRunId)}&name=${encodeURIComponent(artifactName)}`
  }, [apiBase])
  const openArtifact = useCallback(async (item) => {
    const filePath = String(item?.path || '').trim()
    if (!filePath) return
    appDispatch({ type: 'SET_VIEW', view: 'developer' })
    await openFile(filePath)
  }, [appDispatch, openFile])
  const downloadArtifact = useCallback((item, runId) => {
    const url = resolveArtifactActionUrl(item, runId, 'download')
    if (!url) return
    const link = document.createElement('a')
    link.href = url
    const artifactName = String(item?.name || item?.label || '').trim()
    if (artifactName) link.setAttribute('download', artifactName)
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
  }, [resolveArtifactActionUrl])
  const reviewArtifact = useCallback((item) => {
    const filePath = String(item?.path || '').trim()
    if (!filePath) return
    setDiffPreviewPath(filePath)
  }, [])
  const clearActiveRunState = useCallback(() => {
    dispatch({ type: 'SET_STREAMING', val: false })
    dispatch({ type: 'SET_RUN', id: null })
    appDispatch({ type: 'SET_STREAMING', streaming: false })
    appDispatch({ type: 'SET_ACTIVE_RUN', runId: null })
  }, [appDispatch])

  // Close the SSE stream when the panel unmounts (e.g. explicit new-chat remount)
  useEffect(() => {
    return () => { esRef.current?.close() }
  }, [])

  useEffect(() => {
    if (!appState.activeRunId) resumeAttemptedRunRef.current = ''
  }, [appState.activeRunId])

  useEffect(() => {
    if (!chat.awaitingContext || displayableAwaitingContext) return
    dispatch({ type: 'CLEAR_AWAITING' })
  }, [chat.awaitingContext, displayableAwaitingContext])

  useEffect(() => {
    const staleAwaiting = (chat.messages || []).filter((msg) => (
      msg?.role === 'assistant'
      && String(msg?.status || '').trim().toLowerCase() === 'awaiting'
      && String(msg?.runId || '').trim()
      && !messageHasConcreteAwaitingPrompt(msg)
    ))
    if (!staleAwaiting.length) return

    for (const msg of staleAwaiting) {
      const status = String(msg.lastKnownRunStatus || '').trim().toLowerCase()
      const snapshot = {
        status: status || 'running',
        run_id: msg.runId,
        started_at: msg.runStartedAt,
        run_output_dir: msg.runOutputDir,
        log_paths: msg.executionLogPath ? { execution_log: msg.executionLogPath } : {},
        last_error: msg.lastError,
        final_output: msg.content,
      }
      const patch = ACTIVE_RUN_STATUSES.has(status) || !status
        ? buildRunningMessagePatch(snapshot, msg)
        : status === 'awaiting_user_input'
          ? buildInvalidAwaitingErrorPatch(snapshot, msg.runId, msg)
          : status === 'completed'
            ? buildCompletedMessagePatch(snapshot, msg)
            : buildFailedMessagePatch(snapshot, msg.runId, status || 'failed', msg)
      dispatch({ type: 'UPD_MSG', id: msg.id, patch })
    }
  }, [chat.messages])

  useEffect(() => {
    if (chat.streaming || appState.activeRunId) return
    const pendingMsg = [...(chat.messages || [])].reverse().find((msg) => (
      msg?.role === 'assistant'
      && String(msg?.runId || '').trim()
      && isPendingRunStatus(msg?.status)
    ))
    if (!pendingMsg) {
      staleRunRecoveryRef.current = ''
      return
    }

    const runId = String(pendingMsg.runId || '').trim()
    const recoveryKey = `${pendingMsg.id}:${runId}:${pendingMsg.status || ''}`
    if (!runId || staleRunRecoveryRef.current === recoveryKey) return
    staleRunRecoveryRef.current = recoveryKey

    let cancelled = false
    ;(async () => {
      try {
        const resp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(runId)}`)
        const data = await resp.json().catch(() => ({}))
        if (cancelled) return
        if (!resp.ok) {
          dispatch({
            type: 'UPD_MSG',
            id: pendingMsg.id,
            patch: {
              status: 'error',
              statusText: '',
              content: pendingMsg.lastError || failureMessageForRecoveredRun(runId),
            },
          })
          clearActiveRunState()
          return
        }

        dispatch({
          type: 'UPD_MSG',
          id: pendingMsg.id,
          patch: {
            ...runSnapshotMessageMeta(data),
            runStartedAt: data?.started_at || pendingMsg.runStartedAt || new Date().toISOString(),
          },
        })

        const status = runSnapshotStatus(data)
        if (ACTIVE_RUN_STATUSES.has(status)) {
          dispatch({
            type: 'UPD_MSG',
            id: pendingMsg.id,
            patch: {
              ...buildRunningMessagePatch(data, pendingMsg),
              runStartedAt: data?.started_at || pendingMsg.runStartedAt || new Date().toISOString(),
            },
          })
          dispatch({ type: 'CLEAR_AWAITING' })
          dispatch({ type: 'SET_RUN', id: runId })
          appDispatch({ type: 'SET_ACTIVE_RUN', runId })
          appDispatch({ type: 'SET_STREAMING', streaming: true })
          return
        }
        if (status === 'awaiting_user_input') {
          const awaitingPatch = buildAwaitingState(data, pendingMsg)
          if (!awaitingPatch) {
            dispatch({
              type: 'UPD_MSG',
              id: pendingMsg.id,
              patch: buildInvalidAwaitingErrorPatch(data, runId, pendingMsg),
            })
            dispatch({ type: 'CLEAR_AWAITING' })
            return
          }
          dispatch({
            type: 'UPD_MSG',
            id: pendingMsg.id,
            patch: {
              runStartedAt: data?.started_at || pendingMsg.runStartedAt || new Date().toISOString(),
              ...awaitingPatch,
            },
          })
          return
        }

        dispatch({
          type: 'UPD_MSG',
          id: pendingMsg.id,
          patch: status === 'completed'
            ? buildCompletedMessagePatch(data, pendingMsg)
            : buildFailedMessagePatch(data, runId, status, pendingMsg),
        })
        dispatch({ type: 'CLEAR_AWAITING' })
        clearActiveRunState()
      } catch (_) {
        if (cancelled) return
        dispatch({
          type: 'UPD_MSG',
          id: pendingMsg.id,
          patch: {
            status: 'error',
            statusText: '',
            content: pendingMsg.lastError || failureMessageForRecoveredRun(runId),
          },
        })
        dispatch({ type: 'CLEAR_AWAITING' })
        clearActiveRunState()
      }
    })()

    return () => { cancelled = true }
  }, [chat.messages, chat.streaming, appState.activeRunId, apiBase, appDispatch, clearActiveRunState])

  useEffect(() => {
    if ((chat.mode === 'agent' || chat.mode === 'plan') && !selectedModelAgentCapable) {
      dispatch({ type: 'SET_MODE', mode: 'chat' })
    }
  }, [chat.mode, selectedModelAgentCapable])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat.messages])

  useEffect(() => {
    if (!composerMenuOpen) return undefined
    const onMouseDown = (event) => {
      if (composerMenuRef.current && !composerMenuRef.current.contains(event.target)) setComposerMenuOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [composerMenuOpen])

  useEffect(() => {
    if (composerRunActive) setComposerMenuOpen(false)
  }, [composerRunActive])

  useEffect(() => {
    const entries = chat.messages
      .filter(shouldMirrorActivityMessage)
      .map((msg) => buildActivityEntry(msg, { id: `studio:${msg.id}`, source: studioMode ? 'studio' : 'chat' }))
      .filter(Boolean)
    const nextIds = new Set(entries.map((entry) => entry.id))
    for (const entry of entries) {
      appDispatch({ type: 'UPSERT_ACTIVITY_ENTRY', entry })
    }
    const removedIds = mirroredActivityIdsRef.current.filter((id) => !nextIds.has(id))
    if (removedIds.length) {
      appDispatch({ type: 'REMOVE_ACTIVITY_ENTRIES', ids: removedIds })
    }
    mirroredActivityIdsRef.current = Array.from(nextIds)
  }, [chat.messages, appDispatch, studioMode])

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
    if (!chat.messages.length || composerRunActive) return
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
  }, [apiBase, chat.messages, composerRunActive, chatId, contextLimit, saveCurrentSession])

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
    if (chat.mode === 'agent' || chat.mode === 'plan') setMcpEnabled(true)
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
    if (!msg || composerRunActive) return
    if (!isResume && chat.mode === 'research' && dr.kbEnabled) {
      if (!researchKbs.length) {
        window.alert('No knowledge bases found. Create and index one in Super-RAG or `kendr rag` first.')
        return
      }
      const targetKb = dr.kbId ? researchKbs.find(kb => kb.id === dr.kbId) : activeResearchKb
      if (!targetKb) {
        window.alert('No active indexed knowledge base is available. Select an indexed KB or set one active in Super-RAG.')
        return
      }
      if (String(targetKb.status || '').trim().toLowerCase() !== 'indexed') {
        window.alert(`Knowledge base "${targetKb.name || targetKb.id}" is not indexed yet.`)
        return
      }
    }
    setInput('')
    setResumeInput('')

    const runId = `ui-${Date.now().toString(36)}`
    const userMsgId = `u-${runId}`
    const currentAwaitingContext = chat.awaitingContext || null
    const resumeMessageId = String(currentAwaitingContext?.messageId || '').trim()
    const preserveAwaitingBubble = isResume && resumeMessageId && shouldInlineAwaitingContext(currentAwaitingContext)
    const asstMsgId = isResume && resumeMessageId && !preserveAwaitingBubble ? resumeMessageId : `a-${runId}`

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

    if (preserveAwaitingBubble && resumeMessageId) {
      const normalizedReply = msg.toLowerCase()
      const approvalState = normalizedReply === 'approve'
        ? 'approved'
        : normalizedReply === 'cancel'
          ? 'rejected'
          : 'suggested'
      dispatch({
        type: 'UPD_MSG',
        id: resumeMessageId,
        patch: {
          status: 'done',
          approvalState,
        },
      })
    }

    if (isResume && resumeMessageId && !preserveAwaitingBubble) {
      dispatch({
        type: 'UPD_MSG',
        id: asstMsgId,
        patch: {
          content: '',
          status: 'thinking',
          runId: isSimpleStudioChat ? null : runId,
          runStartedAt: new Date().toISOString(),
          logs: [],
          mode: currentMode,
          modeLabel: currentModeLabel,
          statusText: 'Continuing approved plan...',
          approvalScope: '',
          approvalKind: '',
          approvalRequest: null,
          awaitingDecision: '',
          approvalState: '',
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
          logs: [],
          checklist: [],
          status: 'thinking',
          runId: isSimpleStudioChat ? null : runId,
          runStartedAt: new Date().toISOString(),
          mode: currentMode,
          modeLabel: currentModeLabel,
          approvalScope: '',
          approvalKind: '',
          approvalRequest: null,
          awaitingDecision: '',
          approvalState: '',
          ts: new Date(),
        }
      })
    }

    appDispatch({ type: 'SET_STREAMING', streaming: true })

    try {
      const endpoint = isResume && currentAwaitingContext
        ? `${apiBase}/api/chat/resume`
        : isSimpleStudioChat
          ? `${apiBase}/api/chat/simple`
          : `${apiBase}/api/chat`

      const body = isResume && currentAwaitingContext
        ? {
            run_id:      currentAwaitingContext.runId,
            workflow_id: currentAwaitingContext.workflowId,
            text:        msg,
            channel:     'webchat',
          }
        : buildPayload(msg, chatId, runId, appState.projectRoot, chat.mode, dr, sentAttachments, studioMode, mcpEnabled)
      const activePayloadModel = !isResume
        ? (chat.mode === 'research'
          ? effectiveDeepResearchModel
          : (appState.selectedModel ? resolveSelectedModel(appState.selectedModel) : null))
        : null
      if (!isResume && activePayloadModel) {
        const selected = activePayloadModel
        if (selected.provider) body.provider = selected.provider
        if (selected.model) body.model = selected.model
      }
      if (!isResume && chat.mode === 'research' && effectiveDeepResearchModel?.model) {
        body.research_model = effectiveDeepResearchModel.model
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
          clearActiveRunState()
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
          clearActiveRunState()
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
        clearActiveRunState()
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
      clearActiveRunState()
    }
  }, [input, composerRunActive, chat.awaitingContext, chat.mode, apiBase, appState.projectRoot, appState.selectedModel, chatId, dr, attachments, studioMode, isSimpleStudioChat, mcpEnabled, appDispatch, refreshModelInventory, contextLimit, researchKbs, activeResearchKb, clearActiveRunState])

  // ── SSE stream ──────────────────────────────────────────────────────────────
  const openStream = useCallback((runId, asstMsgId) => {
    esRef.current?.close()
    const es = new EventSource(`${apiBase}/api/stream?run_id=${encodeURIComponent(runId)}`)

    let stepCounter = 0
    let closed = false
    let statusPollTimer = null
    const existingMsg = (chat.messages || []).find((msg) => msg?.id === asstMsgId || String(msg?.runId || '').trim() === runId)
    const seenLogSignatures = new Set(
      (Array.isArray(existingMsg?.logs) ? existingMsg.logs : [])
        .map((item) => buildExecutionLogSignature(item))
        .filter(Boolean),
    )
    const fallback = {
      transportErrored: false,
      syncingFile: false,
      logPath: '',
      logContentLength: 0,
      logMtime: 0,
      logBuffer: '',
      parserState: {},
    }

    const closeClean = () => {
      if (closed) return
      closed = true
      if (statusPollTimer) window.clearInterval(statusPollTimer)
      es.close()
      if (esRef.current?.close === closeClean) esRef.current = null
    }

    esRef.current = { close: closeClean }

    const finishStream = () => {
      closeClean()
      clearActiveRunState()
    }

    const pushLogEntry = (item) => {
      const text = String(item?.text || '').trim()
      if (!text) return false
      const entry = {
        id: String(item?.id || `log-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`),
        ts: String(item?.ts || item?.timestamp || new Date().toISOString()),
        clock: String(item?.clock || executionLogClockLabel(item?.ts || item?.timestamp || '')).trim(),
        text,
        category: String(item?.category || 'info').trim() || 'info',
      }
      const signature = buildExecutionLogSignature(entry)
      if (signature && seenLogSignatures.has(signature)) return false
      if (signature) seenLogSignatures.add(signature)
      dispatch({ type: 'ADD_LOG_ENTRY', msgId: asstMsgId, item: entry })
      dispatch({
        type: 'UPD_MSG',
        id: asstMsgId,
        patch: {
          status: 'streaming',
          statusText: text,
        },
      })
      return true
    }

    const applyRunSnapshot = (snapshot, fallbackStatus = '') => {
      if (closed) return
      const data = snapshot && typeof snapshot === 'object' ? snapshot : {}
      const status = runSnapshotStatus(data, fallbackStatus)
      if (status === 'awaiting_user_input') {
        const awaitingPatch = buildAwaitingState(data, existingMsg || {})
        if (!awaitingPatch) {
          dispatch({
            type: 'UPD_MSG',
            id: asstMsgId,
            patch: buildInvalidAwaitingErrorPatch(data, runId, existingMsg || {}),
          })
          dispatch({ type: 'CLEAR_AWAITING' })
          finishStream()
          return
        }
        dispatch({
          type: 'SET_AWAITING',
          ctx: buildAwaitingContext(data, runId, asstMsgId, awaitingPatch),
        })
        dispatch({
          type: 'UPD_MSG',
          id: asstMsgId,
          patch: {
            ...runSnapshotMessageMeta(data),
            ...awaitingPatch,
            artifacts: runSnapshotArtifacts(data),
            checklist: runSnapshotChecklist(data),
          },
        })
        finishStream()
        return
      }

      dispatch({
        type: 'UPD_MSG',
        id: asstMsgId,
        patch: status === 'completed'
          ? buildCompletedMessagePatch(data, existingMsg || {})
          : buildFailedMessagePatch(data, runId, status, existingMsg || {}),
      })
      dispatch({ type: 'CLEAR_AWAITING' })
      finishStream()
    }

    const syncExecutionLogFromFile = async (logPath) => {
      const fileApi = window.kendrAPI?.fs
      if (closed || !fileApi?.readFile) return
      const targetPath = String(logPath || '').trim()
      if (!targetPath || fallback.syncingFile) return
      if (targetPath !== fallback.logPath) {
        fallback.logPath = targetPath
        fallback.logContentLength = 0
        fallback.logMtime = 0
        fallback.logBuffer = ''
        fallback.parserState = {}
      }
      fallback.syncingFile = true
      try {
        if (fileApi?.stat) {
          const stats = await fileApi.stat(targetPath)
          const nextSize = Number(stats?.size || 0)
          const nextMtime = Number(stats?.mtime || 0)
          if (!stats?.error && nextSize === fallback.logContentLength && nextMtime === fallback.logMtime) return
          if (!stats?.error && nextSize < fallback.logContentLength) {
            fallback.logContentLength = 0
            fallback.logMtime = 0
            fallback.logBuffer = ''
            fallback.parserState = {}
          }
        }
        const result = await fileApi.readFile(targetPath)
        if (result?.error) return
        const content = String(result?.content || '')
        if (closed || !content) return
        if (content.length < fallback.logContentLength) {
          fallback.logContentLength = 0
          fallback.logMtime = 0
          fallback.logBuffer = ''
          fallback.parserState = {}
        }
        if (content.length === fallback.logContentLength) return
        const delta = content.slice(fallback.logContentLength)
        fallback.logContentLength = content.length
        if (fileApi?.stat) {
          const stats = await fileApi.stat(targetPath)
          if (!stats?.error) fallback.logMtime = Number(stats?.mtime || fallback.logMtime || 0)
        }
        fallback.logBuffer += delta
        const lines = fallback.logBuffer.split(/\r?\n/)
        fallback.logBuffer = lines.pop() || ''
        for (const line of lines) {
          const entry = parseExecutionLogLine(line, fallback.parserState)
          if (entry) pushLogEntry(entry)
        }
      } catch (_) {
      } finally {
        fallback.syncingFile = false
      }
    }

    const refreshRunSnapshot = async () => {
      if (closed) return
      try {
        const resp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(runId)}`)
        const data = await resp.json().catch(() => ({}))
        if (closed) return
        if (!resp.ok) {
          dispatch({
            type: 'UPD_MSG',
            id: asstMsgId,
            patch: buildFailedMessagePatch(data, runId, 'failed', existingMsg || {}),
          })
          dispatch({ type: 'CLEAR_AWAITING' })
          finishStream()
          return
        }
        dispatch({
          type: 'UPD_MSG',
          id: asstMsgId,
          patch: {
            ...runSnapshotMessageMeta(data),
          },
        })
        const logPath = resolveRunSnapshotLogPath(data)
        if (logPath) await syncExecutionLogFromFile(logPath)
        const status = runSnapshotStatus(data)
        if (TERMINAL_RUN_STATUSES.has(status) || status === 'awaiting_user_input') {
          applyRunSnapshot(data, status)
          return
        }
        if (ACTIVE_RUN_STATUSES.has(status)) {
          dispatch({
            type: 'UPD_MSG',
            id: asstMsgId,
            patch: {
              ...buildRunningMessagePatch(data, {
                ...(existingMsg || {}),
                statusText: fallback.transportErrored
                  ? 'Reconnected to background run. Checking execution log...'
                  : existingMsg?.statusText,
              }),
            },
          })
          dispatch({ type: 'CLEAR_AWAITING' })
          fallback.transportErrored = false
        }
      } catch (_) {
      }
    }

    statusPollTimer = window.setInterval(() => { refreshRunSnapshot() }, 2000)
    refreshRunSnapshot()

    es.addEventListener('status', e => {
      try {
        const d = JSON.parse(e.data)
        if (d.status && d.status !== 'connected') {
          fallback.transportErrored = false
          dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { statusText: sanitizeStatusMessage(d.message || d.status) } })
          dispatch({
            type: 'ADD_PROGRESS',
            msgId: asstMsgId,
            item: {
              id: 'runtime-status',
              slot: 'runtime-status',
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

    es.addEventListener('log', e => {
      try {
        const item = JSON.parse(e.data)
        fallback.transportErrored = false
        pushLogEntry({
          id: item.id || `log-${Date.now()}`,
          ts: item.timestamp || new Date().toISOString(),
          clock: item.clock || '',
          text: item.text || '',
          category: item.category || 'info',
        })
      } catch (_) {}
    })

    es.addEventListener('delta', e => {
      try {
        const d = JSON.parse(e.data)
        if (!d.delta) return
        fallback.transportErrored = false
        dispatch({ type: 'APPEND_MSG_CONTENT', id: asstMsgId, delta: String(d.delta) })
        dispatch({ type: 'UPD_MSG', id: asstMsgId, patch: { status: 'streaming' } })
      } catch (_) {}
    })

    es.addEventListener('result', e => {
      try {
        const d = JSON.parse(e.data)
        const awaitingSignal = runSnapshotSignalsAwaiting(d)
        if (awaitingSignal) {
          const awaitingSnapshot = { ...d, status: 'awaiting_user_input', run_id: runId }
          const awaitingPatch = buildAwaitingState(awaitingSnapshot, existingMsg || {})
          if (!awaitingPatch) {
            dispatch({
              type: 'UPD_MSG',
              id: asstMsgId,
              patch: buildInvalidAwaitingRunningPatch(
                { ...d, status: 'running', run_id: runId },
                existingMsg || {},
              ),
            })
            dispatch({ type: 'CLEAR_AWAITING' })
            refreshRunSnapshot()
            return
          }
          dispatch({
            type: 'SET_AWAITING',
            ctx: buildAwaitingContext(awaitingSnapshot, runId, asstMsgId, awaitingPatch),
          })
          dispatch({
            type: 'UPD_MSG',
            id: asstMsgId,
            patch: {
              ...runSnapshotMessageMeta(awaitingSnapshot),
              ...awaitingPatch,
              artifacts: d.artifact_files || [],
              checklist: runSnapshotChecklist(d),
            },
          })
          return
        }

        dispatch({
          type: 'UPD_MSG',
          id: asstMsgId,
          patch: buildCompletedMessagePatch({ ...d, status: 'completed', run_id: runId }, existingMsg || {}),
        })
        dispatch({ type: 'CLEAR_AWAITING' })
      } catch (_) {}
    })

    es.addEventListener('done', e => {
      let shouldFinish = true
      try {
        const d = JSON.parse(e.data)
        const awaitingSignal = runSnapshotSignalsAwaiting(d)
        if (awaitingSignal) {
          const awaitingSnapshot = { ...d, status: 'awaiting_user_input', run_id: runId }
          const awaitingPatch = buildAwaitingState(awaitingSnapshot, existingMsg || {})
          if (!awaitingPatch) {
            dispatch({
              type: 'UPD_MSG',
              id: asstMsgId,
              patch: buildInvalidAwaitingRunningPatch(
                { ...d, status: 'running', run_id: runId },
                existingMsg || {},
              ),
            })
            dispatch({ type: 'CLEAR_AWAITING' })
            shouldFinish = false
            refreshRunSnapshot()
            return
          }
          dispatch({
            type: 'SET_AWAITING',
            ctx: buildAwaitingContext(awaitingSnapshot, runId, asstMsgId, awaitingPatch),
          })
          dispatch({
            type: 'UPD_MSG',
            id: asstMsgId,
            patch: {
              ...runSnapshotMessageMeta(awaitingSnapshot),
              ...awaitingPatch,
            },
          })
          return
        }

        const normalized = runSnapshotStatus({ ...d, run_id: runId })
        dispatch({
          type: 'UPD_MSG',
          id: asstMsgId,
          patch: normalized === 'completed'
            ? buildCompletedMessagePatch({ ...d, status: 'completed', run_id: runId }, existingMsg || {})
            : buildFailedMessagePatch({ ...d, status: normalized, run_id: runId }, runId, normalized, existingMsg || {}),
        })
        dispatch({ type: 'CLEAR_AWAITING' })
      } catch (_) {}
      if (shouldFinish) finishStream()
    })

    es.addEventListener('error', e => {
      const payload = String(e?.data || '').trim()
      if (!payload) return
      try {
        const d = JSON.parse(payload)
        dispatch({
          type: 'UPD_MSG',
          id: asstMsgId,
          patch: {
            ...runSnapshotMessageMeta({ ...d, status: 'failed', run_id: runId }),
            content: d.message || 'Run failed.',
            status: 'error',
          },
        })
      } catch (_) {
        dispatch({
          type: 'UPD_MSG',
          id: asstMsgId,
          patch: {
            ...runSnapshotMessageMeta({ status: 'failed', run_id: runId }),
            status: 'error',
          },
        })
      }
      refreshModelInventory(true)
      finishStream()
    })

    es.onerror = () => {
      if (closed) return
      fallback.transportErrored = true
      dispatch({
        type: 'UPD_MSG',
        id: asstMsgId,
        patch: {
          status: 'streaming',
          statusText: 'Run stream interrupted. Checking backend status...',
        },
      })
      refreshRunSnapshot()
    }
  }, [apiBase, appDispatch, refreshModelInventory, chat.messages, clearActiveRunState])

  // Re-attach to an active background run when returning to chat view.
  useEffect(() => {
    const activeRunId = String(appState.activeRunId || '').trim()
    if (!activeRunId) return
    if (resumeAttemptedRunRef.current === activeRunId) return
    resumeAttemptedRunRef.current = activeRunId

    let cancelled = false
    ;(async () => {
      try {
        const existing = (chat.messages || []).find(m => String(m.runId || '') === activeRunId)
        const resp = await fetch(`${apiBase}/api/runs/${encodeURIComponent(activeRunId)}`)
        const data = await resp.json().catch(() => ({}))
        if (cancelled) return
        if (!resp.ok) {
          if (existing?.id) {
            dispatch({
              type: 'UPD_MSG',
              id: existing.id,
              patch: buildFailedMessagePatch(data, activeRunId, 'failed', existing),
            })
          }
          dispatch({ type: 'CLEAR_AWAITING' })
          clearActiveRunState()
          return
        }
        const status = runSnapshotStatus(data)
        if (TERMINAL_RUN_STATUSES.has(status)) {
          if (existing?.id) {
            dispatch({
              type: 'UPD_MSG',
              id: existing.id,
              patch: status === 'completed'
                ? buildCompletedMessagePatch(data, existing)
                : buildFailedMessagePatch(data, activeRunId, status, existing),
            })
          }
          dispatch({ type: 'CLEAR_AWAITING' })
          clearActiveRunState()
          return
        }

        let asstMsgId = ''
        if (status === 'awaiting_user_input' && !buildAwaitingState(data, existing || {})) {
          if (existing?.id) {
            dispatch({
              type: 'UPD_MSG',
              id: existing.id,
              patch: buildInvalidAwaitingErrorPatch(data, activeRunId, existing),
            })
          }
          dispatch({ type: 'CLEAR_AWAITING' })
          clearActiveRunState()
          return
        }
        if (existing?.id) {
          const awaitingPatch = status === 'awaiting_user_input' ? buildAwaitingState(data, existing) : null
          asstMsgId = existing.id
          dispatch({
            type: 'UPD_MSG',
            id: asstMsgId,
            patch: {
              ...(status === 'awaiting_user_input'
                ? {
                    ...runSnapshotMessageMeta(data),
                    ...awaitingPatch,
                    status: 'awaiting',
                  }
                : buildRunningMessagePatch(data, existing)),
            },
          })
          if (status === 'awaiting_user_input' && awaitingPatch) {
            dispatch({
              type: 'SET_AWAITING',
              ctx: buildAwaitingContext(data, activeRunId, asstMsgId, awaitingPatch),
            })
          }
          if (status !== 'awaiting_user_input') dispatch({ type: 'CLEAR_AWAITING' })
        } else {
          const awaitingPatch = status === 'awaiting_user_input' ? buildAwaitingState(data) : null
          asstMsgId = `a-${activeRunId}-resume`
          dispatch({
            type: 'ADD_MSG',
            msg: {
              id: asstMsgId,
              role: 'assistant',
              content: '',
              steps: [],
              progress: [],
              logs: [],
              status: status === 'awaiting_user_input' ? 'awaiting' : 'streaming',
              runId: activeRunId,
              runStartedAt: data?.started_at || new Date().toISOString(),
              runOutputDir: String(data?.run_output_dir || data?.output_dir || data?.resume_output_dir || '').trim(),
              executionLogPath: resolveRunSnapshotLogPath(data),
              lastKnownRunStatus: runSnapshotStatus(data),
              lastError: runSnapshotErrorText(data, activeRunId, status),
              mode: chat.mode,
              modeLabel: modeLabel(chat.mode),
              approvalScope: awaitingPatch?.approvalScope || '',
              approvalKind: awaitingPatch?.approvalKind || '',
              approvalRequest: awaitingPatch?.approvalRequest || null,
              awaitingDecision: awaitingPatch?.awaitingDecision || 'reply',
              approvalState: awaitingPatch?.approvalState || '',
              ts: new Date(),
              ...(status === 'awaiting_user_input' ? awaitingPatch : {}),
            },
          })
          if (status === 'awaiting_user_input' && awaitingPatch) {
            dispatch({
              type: 'SET_AWAITING',
              ctx: buildAwaitingContext(data, activeRunId, asstMsgId, awaitingPatch),
            })
          }
        }
        dispatch({ type: 'SET_RUN', id: activeRunId })
        if (status !== 'awaiting_user_input') dispatch({ type: 'CLEAR_AWAITING' })
        dispatch({ type: 'SET_STREAMING', val: status !== 'awaiting_user_input' })
        appDispatch({ type: 'SET_STREAMING', streaming: status !== 'awaiting_user_input' })
        openStream(activeRunId, asstMsgId)
      } catch (_) {
      }
    })()

    return () => { cancelled = true }
  }, [appState.activeRunId, apiBase, openStream, chat.messages, chat.mode, appDispatch, clearActiveRunState])

  // ── Stop run ────────────────────────────────────────────────────────────────
  const stopRun = useCallback(async () => {
    const runId = String(stopTargetRunId || '').trim()
    if (!runId) return
    esRef.current?.close()
    // Mark the matching in-progress bubble as done so it doesn't stay stuck in "Running"
    const activeMsg = [...(chat.messages || [])].reverse().find((msg) => (
      String(msg?.runId || '').trim() === runId && isPendingRunStatus(msg?.status)
    ))
    if (activeMsg) {
      dispatch({ type: 'UPD_MSG', id: activeMsg.id, patch: { status: 'done' } })
    }
    dispatch({ type: 'CLEAR_AWAITING' })
    if (runId) {
      await fetch(`${apiBase}/api/runs/stop`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId })
      }).catch(() => {})
    }
    clearActiveRunState()
  }, [stopTargetRunId, chat.messages, apiBase, clearActiveRunState])

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
    if (chat.mode === 'research' && effectiveDeepResearchModel?.model) {
      return `Research · ${effectiveDeepResearchModel.shortLabel || composerModelMeta.label}`
    }
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
    { id: 'plan',     label: '🗺 Plan' },
    { id: 'agent',    label: '✨ Agent' },
    { id: 'research', label: '🔬 Deep Research' },
  ]
  const showLandingLayout = minimalStudio && !hasMessages
  const composerBanner = composerRunActive
    ? 'Run active. Live execution log updates are streaming in the current run bubble. Stop the run before sending another message.'
    : displayableAwaitingContext
      ? 'Run paused for your input. Reply here to continue the same workflow.'
      : ''

  return (
    <div className={`kc-panel${fullWidth ? ' kc-panel--full' : ''}${showLandingLayout ? ' kc-panel--landing' : ''}${chat.mode === 'research' ? ' kc-panel--research-active' : ''}`}>
      {/* ── Header ── */}
      {!hideHeader && <div className="kc-header">
        <div className="kc-logo">K<span>endr</span></div>
        <div className="kc-header-model" title={studioModelLabel}>
          <span className={`kc-header-model-dot ${composerModelMeta.isLocal || String(modelInventory?.configured_provider || '').toLowerCase() === 'ollama' ? 'local' : ''}`} />
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
      {!minimalStudio && (
        <div className="kc-mode-bar">
          {MODES.map((m) => {
            const requiresAgent = m.id === 'agent' || m.id === 'plan'
            const disabled = requiresAgent && !selectedModelAgentCapable
            return (
              <button
                key={m.id}
                className={`kc-mode-pill ${chat.mode === m.id ? 'kc-mode-pill--active' : ''} ${disabled ? 'kc-mode-pill--disabled' : ''}`}
                onClick={() => { if (disabled) return; dispatch({ type: 'SET_MODE', mode: m.id }) }}
                title={disabled ? 'Selected model cannot run planning or agent workflows.' : ''}
              >{m.label}</button>
            )
          })}
        </div>
      )}

      {minimalStudio && hasMessages && studioAccessory && (
        <div className="kc-compact-toolbar">
          {studioAccessory}
        </div>
      )}

      <div className={`kc-conversation-shell${chat.mode === 'research' ? ' kc-conversation-shell--research' : ''}`}>
        {/* ── Messages ── */}
        <div className="kc-messages">
          {chat.messages.length === 0 && (
            <>
              {minimalStudio && studioAccessory && <div className="kc-landing-accessory">{studioAccessory}</div>}
              <WelcomeScreen minimal={minimalStudio} onSuggest={s => { setInput(s); inputRef.current?.focus() }} />
            </>
          )}

          {chat.messages.map(msg =>
            msg.role === 'user'
              ? <UserMessage key={msg.id} msg={msg} />
              : <AssistantMessage key={msg.id} msg={msg} onQuickReply={(reply) => send(reply, true)} onSendSuggestion={(reply) => send(reply, true)} onOpenArtifact={openArtifact} onDownloadArtifact={downloadArtifact} onReviewArtifact={reviewArtifact} />
          )}
          <div ref={messagesEndRef} />
        </div>

        {chat.mode === 'research' && (
          <DeepResearchPanel
            dr={dr}
            updateDr={updateDr}
            collapsed={dr.collapsed}
            modelOptions={deepResearchModelState.options}
            inheritedModel={deepResearchModelState.inheritedOption}
            inheritedReason={deepResearchModelState.inheritedReason}
            effectiveModel={deepResearchModelState.effectiveOption}
            effectiveModelSource={deepResearchModelState.effectiveSource}
            indexedKbs={indexedResearchKbs}
            activeKb={activeResearchKb}
            selectedKb={selectedResearchKb}
            projectRoot={appState.projectRoot}
            apiBase={apiBase}
            refreshKbs={loadResearchKbs}
          />
        )}
      </div>

      <GitDiffPreview
        cwd={appState.projectRoot}
        filePath={diffPreviewPath}
        onClose={() => setDiffPreviewPath('')}
        onOpenFile={(filePath) => openArtifact({ path: filePath })}
      />

      {/* ── Agent approval modal ── */}
      {displayableAwaitingContext && !inlineAwaiting && (
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
        {!!composerBanner && (
          <div className={`kc-composer-state${composerRunActive ? ' kc-composer-state--running' : ' kc-composer-state--awaiting'}`}>
            {composerBanner}
          </div>
        )}
        {(showInlineAttachmentTools || attachments.length > 0) && (
          <div className="kc-attach-bar">
            {showInlineAttachmentTools && (
              <div className="kc-attach-actions">
                <button className="kc-attach-btn" onClick={attachFiles} disabled={composerRunActive}>+ Files</button>
                {studioMode && <button className="kc-attach-btn" onClick={attachFolder} disabled={composerRunActive}>+ Folder</button>}
                {chat.mode === 'agent' || chat.mode === 'plan' ? (
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
                    disabled={composerRunActive}
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
            )}
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
        )}
        {!studioMode && appState.projectRoot && (
          <div className="kc-project-badge">
            <span>📁 {appState.projectRoot.split(/[\\/]/).pop()}</span>
          </div>
        )}
        {showInlineContextTools && (
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
            <button className="kc-attach-btn" onClick={compactContext} title="Compact context and continue in a fresh backend session" disabled={composerRunActive}>
              Compact
            </button>
          </div>
        )}
        {(showPlanSuggestion || showActiveWorkflowChip) && (
          <div className="kc-smart-tools">
            {showPlanSuggestion && (
              <button className="kc-smart-chip kc-smart-chip--suggest" onClick={() => dispatch({ type: 'SET_MODE', mode: 'plan' })}>
                Create a plan
              </button>
            )}
            {showActiveWorkflowChip && (
              <button
                className="kc-smart-chip kc-smart-chip--active"
                onClick={() => dispatch({ type: 'SET_MODE', mode: 'chat' })}
              >
                {chat.mode === 'plan' ? 'Plan mode on' : chat.mode === 'agent' ? 'Agent mode on' : 'Deep research on'}
              </button>
            )}
          </div>
        )}
        <div className="kc-input-row">
          {minimalStudio && (
            <div className="kc-composer-menu" ref={composerMenuRef}>
              <button className="kc-composer-plus" onClick={() => setComposerMenuOpen((value) => !value)} title="Add files or tools" disabled={composerRunActive}>
                +
              </button>
              {composerMenuOpen && (
                <div className="kc-composer-pop">
                  <button className="kc-composer-pop-item" onClick={() => { setComposerMenuOpen(false); attachFiles() }}>
                    <span className="kc-composer-pop-main"><PaperclipIcon /><span>Add files</span></span>
                  </button>
                  {studioMode && (
                    <button className="kc-composer-pop-item" onClick={() => { setComposerMenuOpen(false); attachFolder() }}>
                      <span className="kc-composer-pop-main"><FolderIcon /><span>Add folder</span></span>
                    </button>
                  )}
                  <div className="kc-composer-pop-sep" />
                  <button
                    className={`kc-composer-pop-item ${chat.mode === 'plan' ? 'active' : ''}${!selectedModelAgentCapable ? ' kc-composer-pop-item--disabled' : ''}`}
                    onClick={() => {
                      if (!selectedModelAgentCapable) return
                      dispatch({ type: 'SET_MODE', mode: chat.mode === 'plan' ? 'chat' : 'plan' })
                      setComposerMenuOpen(false)
                    }}
                    title={!selectedModelAgentCapable ? 'Selected model cannot run planning workflows.' : ''}
                  >
                    <span className="kc-composer-pop-main"><PlanModeIcon /><span>Plan mode</span></span>
                    {chat.mode === 'plan' && <span className="kc-composer-pop-badge">On</span>}
                  </button>
                  <button
                    className={`kc-composer-pop-item ${chat.mode === 'agent' ? 'active' : ''}${!selectedModelAgentCapable ? ' kc-composer-pop-item--disabled' : ''}`}
                    onClick={() => {
                      if (!selectedModelAgentCapable) return
                      dispatch({ type: 'SET_MODE', mode: chat.mode === 'agent' ? 'chat' : 'agent' })
                      setComposerMenuOpen(false)
                    }}
                    title={!selectedModelAgentCapable ? 'Selected model cannot run agent workflows.' : ''}
                  >
                    <span className="kc-composer-pop-main"><AgentModeIcon /><span>Agent mode</span></span>
                    {chat.mode === 'agent' && <span className="kc-composer-pop-badge">On</span>}
                  </button>
                  <button
                    className={`kc-composer-pop-item ${chat.mode === 'research' ? 'active' : ''}`}
                    onClick={() => {
                      dispatch({ type: 'SET_MODE', mode: chat.mode === 'research' ? 'chat' : 'research' })
                      setComposerMenuOpen(false)
                    }}
                  >
                    <span className="kc-composer-pop-main"><ResearchModeIcon /><span>Deep research</span></span>
                    {chat.mode === 'research' && <span className="kc-composer-pop-badge">On</span>}
                  </button>
                  <div className="kc-composer-pop-sep" />
                  <button
                    className={`kc-composer-pop-item ${mcpEnabled ? 'active' : ''}`}
                    onClick={() => {
                      setMcpEnabled((value) => !value)
                      setComposerMenuOpen(false)
                    }}
                  >
                    <span className="kc-composer-pop-main"><PlugModeIcon /><span>MCP {mcpEnabled ? 'on' : 'off'}</span></span>
                  </button>
                </div>
              )}
            </div>
          )}
          <textarea
            ref={inputRef}
            className="kc-input"
            placeholder={
              minimalStudio
                ? (chat.mode === 'plan'
                    ? 'Ask for a plan first. Kendr will outline the steps before doing the work…'
                    : 'Search, ask, or tell Kendr what to do…')
                :
              chat.mode === 'research'  ? 'Describe the deep research task, scope, and output you want…'  :
              chat.mode === 'plan'      ? 'Ask for a plan first. Kendr will outline steps and wait before implementation… (Ctrl+Enter)' :
              chat.mode === 'security'  ? 'Describe the target and scope…'     :
              chat.mode === 'agent'     ? 'Ask the agent to investigate, reason step by step, and do the detailed work… (Ctrl+Enter)' :
              'Ask a direct question… (Ctrl+Enter)'
            }
            value={input}
            onChange={e => setInput(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={handleKey}
            rows={minimalStudio ? 1 : 3}
            disabled={composerRunActive}
          />
          <button
            className={`kc-send-btn ${composerRunActive ? 'kc-send-btn--stop' : ''}`}
            onClick={composerRunActive ? () => stopRun() : () => send()}
            disabled={!composerRunActive && !input.trim()}
            title={composerRunActive ? 'Stop active run' : 'Send (Ctrl+Enter)'}
          >
            {composerRunActive ? 'Stop' : <SendIcon />}
          </button>
        </div>
        {showInlineFlowStrip && (
          <div className="kc-flow-strip">
            <span className={`kc-flow-chip kc-flow-chip--${chat.mode}`}>{chat.mode === 'plan' ? 'Plan first' : chat.mode === 'agent' ? 'Agent run' : chat.mode === 'research' ? 'Research flow' : 'Quick answer'}</span>
            {!studioMode && appState.projectRoot && <span className="kc-flow-chip">Workspace · {basename(appState.projectRoot)}</span>}
            <span className="kc-flow-chip">{composerModelMeta.model ? composerModelMeta.label : 'Backend auto'}</span>
            {chat.mode === 'plan' && <span className="kc-flow-chip kc-flow-chip--muted">waits before implement</span>}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Deep Research Panel ──────────────────────────────────────────────────────
function DeepResearchPanel({
  dr,
  updateDr,
  collapsed = false,
  modelOptions = [],
  inheritedModel = null,
  inheritedReason = '',
  effectiveModel = null,
  effectiveModelSource = 'none',
  indexedKbs = [],
  activeKb = null,
  selectedKb = null,
  projectRoot = '',
  apiBase = '',
  refreshKbs = null,
}) {
  const api = window.kendrAPI
  const [kbSetupState, setKbSetupState] = useState({ status: 'idle', message: '' })
  const depthPreset = resolveDeepResearchDepthPreset(dr.depthMode, dr.pages)

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

  const defaultKbName = (() => {
    const seed = dr.localPaths[0] || projectRoot || 'Research'
    const base = basename(seed).replace(/\.[^.]+$/, '').trim() || 'Research'
    return `${base} KB`
  })()

  const openSuperRag = (params = {}) => {
    const target = new URL('/rag', apiBase || window.location.origin)
    Object.entries(params).forEach(([key, value]) => {
      if (value == null || value === '') return
      target.searchParams.set(key, String(value))
    })
    window.open(target.toString(), '_blank', 'noopener,noreferrer')
  }

  const watchKbIndex = useCallback(async (kbId, kbName) => {
    const pause = (ms) => new Promise(resolve => setTimeout(resolve, ms))
    for (let attempt = 0; attempt < 48; attempt += 1) {
      await pause(2500)
      try {
        const statusResp = await fetch(`${apiBase}/api/rag/kbs/${encodeURIComponent(kbId)}/index/status`)
        const statusData = await statusResp.json().catch(() => ({}))
        const latest = typeof refreshKbs === 'function' ? await refreshKbs() : []
        const latestKb = Array.isArray(latest) ? latest.find(kb => kb.id === kbId) : null
        const kbStatus = String(latestKb?.status || '').trim().toLowerCase()
        if (statusData?.status === 'running' || kbStatus === 'indexing') {
          setKbSetupState({
            status: 'indexing',
            message: `Active KB "${kbName}" is indexing${statusData?.chunks_indexed ? ` (${statusData.chunks_indexed} chunks so far)` : ''}.`,
          })
          continue
        }
        if (statusData?.status === 'done' || statusData?.status === 'done_with_errors' || kbStatus === 'indexed') {
          setKbSetupState({
            status: kbStatus === 'indexed' ? 'ready' : 'warning',
            message: kbStatus === 'indexed'
              ? `Active KB "${kbName}" is ready for Deep Research.`
              : `KB "${kbName}" finished indexing with warnings. Check Super-RAG if results look incomplete.`,
          })
          return
        }
        if (statusData?.status === 'error') {
          setKbSetupState({
            status: 'error',
            message: `KB "${kbName}" failed to index. Open Super-RAG to inspect the source setup.`,
          })
          return
        }
      } catch (_) {
      }
    }
    setKbSetupState({
      status: 'indexing',
      message: `KB setup started for "${kbName}". Indexing is still running; you can monitor it in Super-RAG.`,
    })
  }, [apiBase, refreshKbs])

  const quickCreateActiveKb = useCallback(async () => {
    const promptName = window.prompt('Name for the new active knowledge base:', defaultKbName)
    const kbName = String(promptName || '').trim()
    if (!kbName) return
    setKbSetupState({ status: 'working', message: `Creating "${kbName}"…` })
    try {
      const createResp = await fetch(`${apiBase}/api/rag/kbs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: kbName,
          description: 'Created from Deep Research quick setup.',
        }),
      })
      const createdKb = await createResp.json().catch(() => ({}))
      if (!createResp.ok || createdKb?.error || !createdKb?.id) {
        throw new Error(createdKb?.error || 'Failed to create knowledge base.')
      }

      for (const path of dr.localPaths || []) {
        const sourceResp = await fetch(`${apiBase}/api/rag/kbs/${encodeURIComponent(createdKb.id)}/sources`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            type: 'folder',
            path,
            label: basename(path) || path,
            recursive: true,
            max_files: 300,
          }),
        })
        const sourceData = await sourceResp.json().catch(() => ({}))
        if (!sourceResp.ok || sourceData?.error) {
          throw new Error(sourceData?.error || `Failed to add source: ${path}`)
        }
      }

      const activateResp = await fetch(`${apiBase}/api/rag/kbs/${encodeURIComponent(createdKb.id)}/activate`, { method: 'POST' })
      const activateData = await activateResp.json().catch(() => ({}))
      if (!activateResp.ok || activateData?.error) {
        throw new Error(activateData?.error || 'Failed to activate knowledge base.')
      }

      updateDr({ kbEnabled: true, kbId: '' })
      if (typeof refreshKbs === 'function') await refreshKbs()

      if ((dr.localPaths || []).length) {
        const indexResp = await fetch(`${apiBase}/api/rag/kbs/${encodeURIComponent(createdKb.id)}/index`, { method: 'POST' })
        if (!indexResp.ok) {
          throw new Error('Knowledge base created, but indexing could not be started.')
        }
        setKbSetupState({
          status: 'indexing',
          message: `Active KB "${kbName}" created from ${dr.localPaths.length} folder${dr.localPaths.length === 1 ? '' : 's'}. Indexing started.`,
        })
        watchKbIndex(createdKb.id, kbName)
      } else {
        setKbSetupState({
          status: 'warning',
          message: `Active KB "${kbName}" was created, but it has no sources yet. Add a folder in Super-RAG to finish setup.`,
        })
        openSuperRag({ kb: createdKb.id })
      }
    } catch (err) {
      setKbSetupState({
        status: 'error',
        message: String(err?.message || err || 'KB setup failed.'),
      })
    }
  }, [apiBase, defaultKbName, dr.localPaths, openSuperRag, refreshKbs, updateDr, watchKbIndex])

  return (
    <div className={`dr-panel${collapsed ? ' dr-panel--collapsed' : ''}`}>
      <div className="dr-panel-inner">
        <div className="dr-panel-header" onClick={() => updateDr({ collapsed: !dr.collapsed })}>
          <span className="dr-panel-title">🔬 Deep Research Settings</span>
          <div className="dr-summary">
            <span className="dr-sum-pill">{depthPreset.summary}</span>
            {effectiveModel?.model && <span className="dr-sum-pill">{effectiveModel.model}</span>}
            <span className="dr-sum-pill">{dr.citationStyle.toUpperCase()}</span>
            <span className="dr-sum-pill">{dr.outputFormats.join('·')}</span>
            {dr.webSearchEnabled && effectiveModel?.model && (
              <span className="dr-sum-pill">
                {hasNativeWebSearchCapability(effectiveModel.provider, effectiveModel.model, effectiveModel.capabilities)
                  ? 'Native web'
                  : 'Kendr search'}
              </span>
            )}
            {!dr.webSearchEnabled && <span className="dr-sum-pill dr-sum-warn">Local only</span>}
          </div>
          <span className="dr-collapse-btn">{dr.collapsed ? '▸' : '▾'}</span>
        </div>

        {!dr.collapsed && (
          <div className="dr-body">
            {/* Row 1 */}
            <div className="dr-grid">
              <div className="dr-field">
                <label className="dr-label">Research Depth</label>
                <select
                  className="dr-select"
                  value={depthPreset.id}
                  onChange={e => {
                    const preset = resolveDeepResearchDepthPreset(e.target.value, 0)
                    updateDr({ depthMode: preset.id, pages: preset.pages })
                  }}
                >
                  {DEEP_RESEARCH_DEPTH_PRESETS.map((preset) => (
                    <option key={preset.id} value={preset.id}>{preset.label}</option>
                  ))}
                </select>
                <div className="dr-note">{depthPreset.hint}</div>
                <div className="dr-note">Kendr uses this as an execution-depth hint. The final exports are sized automatically from source density, citations, and structure instead of targeting an exact page count.</div>
              </div>
              <div className="dr-field">
                <label className="dr-label">Deep Research Model</label>
                <select
                  className="dr-select"
                  value={dr.researchModel || ''}
                  onChange={e => updateDr({ researchModel: e.target.value })}
                >
                  <option value="">
                    {inheritedModel?.shortLabel
                      ? `Use selected chat model · ${inheritedModel.shortLabel}`
                      : 'Use the chat header model'}
                  </option>
                  {modelOptions.map(option => (
                    <option
                      key={option.value}
                      value={option.value}
                      disabled={!!option.disabledReason}
                    >
                      {option.disabledReason
                        ? `${option.shortLabel} — ${option.disabledReason}`
                        : option.shortLabel}
                    </option>
                  ))}
                </select>
                <div className="dr-note">
                  {effectiveModel
                    ? `Active for Deep Research: ${effectiveModel.shortLabel}${effectiveModelSource === 'recommended' ? ' (recommended)' : effectiveModelSource === 'header' ? ' (from header model)' : ''}.`
                    : 'No compatible Deep Research model is available with the current settings.'}
                </div>
                {dr.webSearchEnabled ? (
                  <div className="dr-note">
                    {effectiveModel && hasNativeWebSearchCapability(effectiveModel.provider, effectiveModel.model, effectiveModel.capabilities)
                      ? 'This model can use native web search for Deep Research.'
                      : 'This model will use Kendr web search fallback: Kendr gathers sources, then the selected model synthesizes the report.'}
                  </div>
                ) : (
                  <div className="dr-note">Local-only runs can use local models or any configured provider with enough context.</div>
                )}
                {!dr.researchModel && inheritedReason && effectiveModel && (
                  <div className="dr-note">The current chat-header model is incompatible here, so this run will fall back to {effectiveModel.shortLabel}.</div>
                )}
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
              />
              <div className="dr-note">
                These exact URLs will be fetched as part of the report, even if general web search is off.
              </div>
            </div>

            <div className="dr-field" style={{ marginTop: 8 }}>
              <label className="dr-label">Private Knowledge</label>
              <div className="dr-checks">
                <label className="dr-check">
                  <input
                    type="checkbox"
                    checked={!!dr.kbEnabled}
                    onChange={e => updateDr({ kbEnabled: e.target.checked })}
                  />
                  Use knowledge base
                </label>
              </div>
              {dr.kbEnabled && (
                <>
                  <div className="dr-path-row" style={{ marginTop: 8 }}>
                    <select
                      className="dr-select"
                      value={dr.kbId || ''}
                      disabled={!indexedKbs.length && !activeKb}
                      onChange={e => updateDr({ kbId: e.target.value })}
                    >
                      <option value="">{activeKb ? `Active KB (${activeKb.name})` : 'Active KB'}</option>
                      {indexedKbs.map(kb => (
                        <option key={kb.id} value={kb.id}>{kb.name}</option>
                      ))}
                    </select>
                    <input
                      className="dr-input-sm"
                      type="number"
                      min={1}
                      max={50}
                      step={1}
                      value={dr.kbTopK || 8}
                      onChange={e => updateDr({ kbTopK: Math.max(1, Number(e.target.value || 8)) })}
                    />
                  </div>
                  <div className="dr-note">
                    Use private indexed docs with web research, local files, or a KB-only run. Empty selector means use the active KB.
                  </div>
                  {!indexedKbs.length && (
                    <div className="dr-note">No indexed knowledge bases found yet. Create one here in one step, or open Super-RAG for the full setup.</div>
                  )}
                  {dr.kbEnabled && !selectedKb && (
                    <div className="dr-note">No active indexed KB is available yet. Set one active in Super-RAG or pick an indexed KB here.</div>
                  )}
                  {dr.kbEnabled && (!indexedKbs.length || !selectedKb) && (
                    <div className="dr-path-row" style={{ marginTop: 8 }}>
                      <button
                        className="dr-action-btn"
                        onClick={quickCreateActiveKb}
                        disabled={kbSetupState.status === 'working' || kbSetupState.status === 'indexing'}
                      >
                        {dr.localPaths.length ? 'Create Active KB From Folders' : 'Create Active KB'}
                      </button>
                      <button
                        className="dr-action-btn"
                        onClick={() => openSuperRag({ quick: 1, name: defaultKbName })}
                      >
                        Open Quick KB Setup
                      </button>
                    </div>
                  )}
                  {dr.kbEnabled && !dr.localPaths.length && (!indexedKbs.length || !selectedKb) && (
                    <div className="dr-note">Tip: add a local folder above, then one click can create, activate, and start indexing the KB for you.</div>
                  )}
                  {kbSetupState.message && (
                    <div className="dr-note">
                      {kbSetupState.message}
                    </div>
                  )}
                  {selectedKb && (
                    <div className="dr-note">
                      KB ready: {selectedKb.name} · {selectedKb.stats?.total_chunks || 0} chunks · top {dr.kbTopK || 8} passages
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Welcome screen ───────────────────────────────────────────────────────────
function WelcomeScreen({ onSuggest, minimal = false }) {
  const SUGGESTIONS = minimal
    ? [
        'Search files on my machine',
        'Research this deeply',
        'Turn this into a plan',
      ]
    : [
        'Summarize the attached files for me',
        'Explain this topic simply',
        'Make a plan before implementing this task',
        'Investigate this problem step by step',
        'Run a security assessment',
        'Write a detailed technical report',
        'Compare two approaches and recommend one',
      ]
  return (
    <div className="kc-welcome">
      {minimal && <div className="kc-welcome-brow">Orchestrate deep work.</div>}
      {!minimal && <div className="kc-welcome-logo">⚡</div>}
      <h2 className={`kc-welcome-title${minimal ? ' kc-welcome-title--hero' : ''}`}>
        {minimal ? (
          <>
            <span>Kendr</span>
            <span className="kc-welcome-title-accent">.</span>
          </>
        ) : 'Kendr Studio'}
      </h2>
      <p className="kc-welcome-sub">
        {minimal
          ? 'Research, route models, and run agents from one workspace.'
          : 'Use Chat for quick answers. Use Plan to outline the work first. Use Agent when you want Kendr to do the detailed work.'}
      </p>
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
function AssistantMessage({ msg, onQuickReply, onSendSuggestion, onOpenArtifact, onDownloadArtifact, onReviewArtifact }) {
  const [copied, setCopied] = useState(false)
  const [nowMs, setNowMs] = useState(Date.now())
  const [logsExpanded, setLogsExpanded] = useState(true)
  const prevLogCountRef = useRef(Array.isArray(msg?.logs) ? msg.logs.length : 0)
  const copy = () => { navigator.clipboard.writeText(msg.content); setCopied(true); setTimeout(() => setCopied(false), 1500) }
  useEffect(() => {
    if (!msg?.runId) return
    if (!['thinking', 'streaming', 'awaiting'].includes(String(msg?.status || ''))) return
    const timer = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [msg?.runId, msg?.status])
  useEffect(() => {
    const nextCount = Array.isArray(msg?.logs) ? msg.logs.length : 0
    const prevCount = prevLogCountRef.current
    if (nextCount > 0 && prevCount === 0 && ['thinking', 'streaming', 'awaiting'].includes(String(msg?.status || ''))) {
      setLogsExpanded(true)
    }
    prevLogCountRef.current = nextCount
  }, [msg?.logs, msg?.status])
  const elapsedSeconds = msg?.runId ? Math.max(0, Math.floor((nowMs - new Date(msg.runStartedAt || msg.ts || Date.now()).getTime()) / 1000)) : 0
  const progress = Array.isArray(msg.progress) ? msg.progress : []
  const logs = Array.isArray(msg.logs) ? msg.logs : []
  const shellCard = shellCardFromProgress(progress)
  const visibleProgress = progress.filter((item) => !isShellProgressItem(item))
  const liveProgressItem = buildLiveProgressItem(visibleProgress, msg.statusText, msg.status)
  const checklist = Array.isArray(msg.checklist) ? msg.checklist : []
  const activityCards = summarizeRunArtifacts(visibleProgress, msg.artifacts)
  const showActivityCards = activityCards.length > 0 && !isPendingRunStatus(msg.status)
  const hasConcreteAwaiting = messageHasConcreteAwaitingPrompt(msg)
  const inlineApprovalVisible = (
    msg.status === 'awaiting'
    && hasConcreteAwaiting
    && !isSkillApproval(msg.approvalKind, msg.approvalRequest)
  )
  const planCardVisible = checklist.length > 0 && (
    msg.mode === 'plan'
    || isPlanApprovalScope(msg.approvalScope, msg.approvalKind, msg.approvalRequest)
  )
  const blockerChips = inferExecutionBlockers({ msg, shellCard, progress: visibleProgress, checklist })

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

        {showActivityCards && (
          <RunArtifactCards cards={activityCards} runId={msg.runId} onOpenItem={onOpenArtifact} onDownloadItem={onDownloadArtifact} onReviewItem={onReviewArtifact} />
        )}

        {msg.runId && ['thinking', 'streaming', 'awaiting'].includes(String(msg.status || '')) && (
          <div className="kc-worklog">
            <div className="kc-worklog-head">
              <span>Working for {formatDuration(elapsedSeconds)}</span>
              <span className="kc-worklog-pill">{liveProgressLabel(liveProgressItem)}</span>
            </div>
            <div className={`kc-worklog-current kc-worklog-current--${liveProgressItem?.status || 'running'}`}>
              <div className="kc-worklog-current-title">
                {liveProgressItem?.title || sanitizeStatusMessage(msg.statusText) || 'Working...'}
              </div>
              {liveProgressItem?.detail && <div className="kc-worklog-current-detail">{liveProgressItem.detail}</div>}
              {(liveProgressItem?.actor || liveProgressItem?.durationLabel || liveProgressItem?.cwd) && (
                <div className="kc-worklog-current-meta">
                  {liveProgressItem?.actor && <span>{liveProgressItem.actor}</span>}
                  {liveProgressItem?.durationLabel && <span>{liveProgressItem.durationLabel}</span>}
                  {liveProgressItem?.cwd && <span>{liveProgressItem.cwd}</span>}
                </div>
              )}
            </div>
          </div>
        )}

        {msg.runId && (logs.length > 0 || ['thinking', 'streaming', 'awaiting'].includes(String(msg.status || ''))) && (
          <ExecutionLogPanel
            logs={logs}
            expanded={logsExpanded}
            onToggle={() => setLogsExpanded((value) => !value)}
          />
        )}

        {/* Step timeline */}
        {msg.steps?.length > 0 && !isPendingRunStatus(msg.status) && (
          <div className="kc-steps">
            {msg.steps.map(step => <StepCard key={step.stepId} step={step} />)}
          </div>
        )}

        {planCardVisible ? (
          <PlanSummaryCard
            msg={msg}
            checklist={checklist}
            onQuickReply={onQuickReply}
            onSendSuggestion={onSendSuggestion}
          />
        ) : inlineApprovalVisible ? (
          <InlineAwaitingCard
            msg={msg}
            onQuickReply={onQuickReply}
            onSendSuggestion={onSendSuggestion}
          />
        ) : checklist.length > 0 ? (
          <ChecklistCard checklist={checklist} />
        ) : null}

        {/* Final content */}
        {msg.content && msg.status !== 'error' && !inlineApprovalVisible && (
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
        {msg.status === 'awaiting' && hasConcreteAwaiting && !inlineApprovalVisible && (
          <div className="kc-awaiting-note">⏳ Waiting for your reply above…</div>
        )}

        <div className="kc-bubble-ts">{formatTs(msg.ts)}</div>
      </div>
    </div>
  )
}

function ExecutionLogPanel({ logs, expanded, onToggle }) {
  const items = Array.isArray(logs) ? logs : []
  const summary = summarizeLogFeed(items)
  return (
    <div className={`kc-log-panel${expanded ? '' : ' kc-log-panel--collapsed'}`}>
      <div className="kc-log-panel-head">
        <div className="kc-log-panel-meta">
          <div className="kc-log-panel-label">Live Execution Log</div>
          <div className="kc-log-panel-summary">{summary}</div>
        </div>
        <button className="kc-log-panel-toggle" onClick={onToggle}>
          {expanded ? 'Collapse' : 'Expand'}
        </button>
      </div>
      {expanded && (
        <div className="kc-log-panel-body">
          {items.length === 0 ? (
            <div className="kc-log-empty">Waiting for execution log output...</div>
          ) : (
            <div className="kc-log-lines">
              {items.slice(-18).map((item) => (
                <div key={item.id} className="kc-log-line">
                  {item.clock && <span className="kc-log-clock">{item.clock}</span>}
                  <span className="kc-log-text">{item.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function RunArtifactCards({ cards, runId, onOpenItem, onDownloadItem, onReviewItem }) {
  return (
    <div className="kc-activity-grid">
      {cards.map((card) => (
        <div key={`${card.kind}-${card.title}`} className={`kc-activity-card kc-activity-card--${card.kind}`}>
          <div className="kc-activity-card-head">
            <div>
              <div className="kc-activity-card-kind">{card.kind}</div>
              <div className="kc-activity-card-title">{card.title}</div>
            </div>
            {card.kind === 'edit' && Array.isArray(card.items) && card.items.some((item) => item?.path) && (
              <button className="kc-activity-card-action" onClick={() => onReviewItem?.(card.items.find((item) => item?.path))}>
                Review
              </button>
            )}
          </div>
          {Array.isArray(card.items) && card.items.length > 0 && (
            <div className={`kc-activity-card-items${card.kind === 'artifact' ? ' kc-activity-card-items--stack' : ''}`}>
              {card.items.slice(0, card.kind === 'artifact' ? 6 : 3).map((item) => (
                card.kind === 'artifact' ? (
                  <div key={`${item.path || item.name || item.label}-${item.label}`} className="kc-activity-card-file">
                    <span className="kc-activity-card-file-label">{item.label}</span>
                    <div className="kc-activity-card-file-actions">
                      {(runId || item?.downloadUrl) && (
                        <button className="kc-activity-card-mini" onClick={() => onDownloadItem?.(item, runId)}>
                          Download
                        </button>
                      )}
                      {item?.path && (
                        <button className="kc-activity-card-mini kc-activity-card-mini--ghost" onClick={() => onOpenItem?.(item)}>
                          Open
                        </button>
                      )}
                    </div>
                  </div>
                ) : item?.path ? (
                  <button key={`${item.path}-${item.label}`} className="kc-activity-card-item kc-activity-card-item--action" onClick={() => onOpenItem?.(item)}>
                    {item.label}
                  </button>
                ) : (
                  <span key={item.label} className="kc-activity-card-item">{item.label}</span>
                )
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function PlanSummaryCard({ msg, checklist, onQuickReply, onSendSuggestion }) {
  const [showSuggest, setShowSuggest] = useState(false)
  const [draft, setDraft] = useState('')
  const approvalRequest = (msg.approvalRequest && typeof msg.approvalRequest === 'object') ? msg.approvalRequest : {}
  const approvalActions = (approvalRequest.actions && typeof approvalRequest.actions === 'object') ? approvalRequest.actions : {}
  const rawSummary = String(approvalRequest.summary || msg.content || '').trim()
  const summary = rawSummary.length > 520 ? `${rawSummary.slice(0, 520).trim()}…` : rawSummary
  const approvalState = String(msg.approvalState || '').trim().toLowerCase()
  const awaiting = msg.status === 'awaiting'
  const stateLabel = awaiting
    ? 'Plan Ready'
    : approvalState === 'approved'
      ? 'Plan Approved'
      : approvalState === 'rejected'
        ? 'Plan Rejected'
        : approvalState === 'suggested'
          ? 'Plan Updated'
          : 'Plan'

  return (
    <div className="kc-plan-card">
      <div className="kc-plan-card-head">
        <div>
          <div className="kc-plan-card-label">{stateLabel}</div>
          <div className="kc-plan-card-meta">{checklist.length} task{checklist.length === 1 ? '' : 's'}</div>
        </div>
        {approvalState && approvalState !== 'pending' && (
          <span className={`kc-plan-card-badge kc-plan-card-badge--${approvalState}`}>{approvalState}</span>
        )}
      </div>
      {summary && <div className="kc-plan-card-summary">{summary}</div>}
      <div className="kc-plan-card-list">
        {checklist.map((item) => (
          <ChecklistItem key={`plan-${item.step}-${item.title}`} item={item} compact />
        ))}
      </div>
      {awaiting && (
        <>
          <div className="kc-plan-card-actions">
            <button className="kc-plan-card-btn kc-plan-card-btn--approve" onClick={() => onQuickReply?.('approve')}>
              {approvalActions.accept_label || 'Implement'}
            </button>
            <button
              className={`kc-plan-card-btn kc-plan-card-btn--ghost${showSuggest ? ' kc-plan-card-btn--active' : ''}`}
              onClick={() => setShowSuggest((value) => !value)}
            >
              {approvalActions.suggest_label || 'Change Plan'}
            </button>
            <button className="kc-plan-card-btn kc-plan-card-btn--reject" onClick={() => onQuickReply?.('cancel')}>
              {approvalActions.reject_label || 'Reject'}
            </button>
          </div>
          {showSuggest && (
            <div className="kc-plan-card-suggest">
              <textarea
                className="kc-plan-card-input"
                rows={3}
                placeholder="Say what should change in the plan…"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
              <button
                className="kc-plan-card-btn kc-plan-card-btn--approve"
                onClick={() => {
                  if (!draft.trim()) return
                  onSendSuggestion?.(draft)
                  setDraft('')
                  setShowSuggest(false)
                }}
                disabled={!draft.trim()}
              >
                Send
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function InlineAwaitingCard({ msg, onQuickReply, onSendSuggestion }) {
  const [showSuggest, setShowSuggest] = useState(false)
  const [draft, setDraft] = useState('')
  const approvalRequest = (msg.approvalRequest && typeof msg.approvalRequest === 'object') ? msg.approvalRequest : {}
  const approvalActions = (approvalRequest.actions && typeof approvalRequest.actions === 'object') ? approvalRequest.actions : {}
  const title = approvalRequest.title || awaitingTitleFromContext(msg.approvalScope, msg.approvalKind, approvalRequest)
  const summary = String(
    approvalRequest.summary
    || msg.content
    || ''
  ).trim()
  const sections = Array.isArray(approvalRequest.sections) ? approvalRequest.sections : []
  const helpText = String(approvalRequest.help_text || '').trim()
  const decisionMode = String(msg.awaitingDecision || (isApprovalLikeAwaiting(msg.approvalScope, msg.approvalKind, approvalRequest) ? 'approval' : 'reply')).trim().toLowerCase()
  const hasQuickActions = decisionMode === 'approval'

  return (
    <div className="kc-inline-approval">
      <div className="kc-inline-approval-head">
        <div className="kc-inline-approval-title">{title}</div>
        <div className="kc-inline-approval-status">awaiting</div>
      </div>
      {summary && (
        <div className="kc-inline-approval-summary">
          <MarkdownRenderer content={summary} />
        </div>
      )}
      {sections.length > 0 && (
        <div className="kc-inline-approval-sections">
          {sections.map((section, index) => (
            <div key={`${section.title || 'section'}-${index}`} className="kc-inline-approval-section">
              {section.title && <div className="kc-inline-approval-section-title">{section.title}</div>}
              {Array.isArray(section.items) && section.items.length > 0 && (
                <ul className="kc-inline-approval-list">
                  {section.items.map((item, itemIndex) => (
                    <li key={`${index}-${itemIndex}`}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
      {helpText && (
        <div className="kc-inline-approval-help">{helpText}</div>
      )}
      {hasQuickActions ? (
        <>
          <div className="kc-inline-approval-actions">
            <button className="kc-plan-card-btn kc-plan-card-btn--approve" onClick={() => onQuickReply?.('approve')}>
              {approvalActions.accept_label || 'Approve'}
            </button>
            <button
              className={`kc-plan-card-btn kc-plan-card-btn--ghost${showSuggest ? ' kc-plan-card-btn--active' : ''}`}
              onClick={() => setShowSuggest((value) => !value)}
            >
              {approvalActions.suggest_label || 'Reply'}
            </button>
            <button className="kc-plan-card-btn kc-plan-card-btn--reject" onClick={() => onQuickReply?.('cancel')}>
              {approvalActions.reject_label || 'Reject'}
            </button>
          </div>
          {showSuggest && (
            <div className="kc-plan-card-suggest">
              <textarea
                className="kc-plan-card-input"
                rows={3}
                placeholder="Type your reply…"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
              <button
                className="kc-plan-card-btn kc-plan-card-btn--approve"
                onClick={() => {
                  if (!draft.trim()) return
                  onSendSuggestion?.(draft)
                  setDraft('')
                  setShowSuggest(false)
                }}
                disabled={!draft.trim()}
              >
                Send
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="kc-plan-card-suggest">
          <textarea
            className="kc-plan-card-input"
            rows={3}
            placeholder="Type your reply…"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button
            className="kc-plan-card-btn kc-plan-card-btn--approve"
            onClick={() => {
              if (!draft.trim()) return
              onSendSuggestion?.(draft)
              setDraft('')
            }}
            disabled={!draft.trim()}
          >
            Send reply
          </button>
        </div>
      )}
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
function PaperclipIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="m21.4 11.1-8.49 8.49a5 5 0 0 1-7.07-7.07l9.19-9.2a3.5 3.5 0 1 1 4.95 4.96L10.76 17.5a2 2 0 1 1-2.83-2.83l8.49-8.48"/></svg>
}
function FolderIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l1.5 2h7.5A1.5 1.5 0 0 1 19 9.5v7a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 16.5z"/></svg>
}
function PlanModeIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M8 6h11"/><path d="M8 12h11"/><path d="M8 18h11"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/></svg>
}
function AgentModeIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v3"/><path d="M7 6h10"/><rect x="5" y="9" width="14" height="9" rx="3"/><path d="M9 13h.01"/><path d="M15 13h.01"/><path d="M9.5 16h5"/></svg>
}
function ResearchModeIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="6"/><path d="m20 20-3.5-3.5"/><path d="M11 8v3l2 2"/></svg>
}
function PlugModeIcon() {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M9 7V3"/><path d="M15 7V3"/><path d="M7 9h10"/><path d="M8 9v3a4 4 0 0 0 8 0V9"/><path d="M12 16v5"/></svg>
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
