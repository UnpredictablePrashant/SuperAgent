function basename(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const normalized = raw.replace(/\\/g, '/')
  const parts = normalized.split('/').filter(Boolean)
  return parts.length ? parts[parts.length - 1] : normalized
}

function pushUniqueLabel(list, value, limit = 4) {
  const next = String(value || '').trim()
  if (!next || list.some((item) => item.label === next) || list.length >= limit) return
  list.push({ label: next, path: '' })
}

function pushUniqueItem(list, item, limit = 4) {
  const label = String(item?.label || '').trim()
  const path = String(item?.path || '').trim()
  if (!label || list.length >= limit) return
  if (list.some((entry) => entry.label === label && String(entry.path || '').trim() === path)) return
  list.push({
    label,
    path,
    name: String(item?.name || label).trim(),
    kind: String(item?.kind || '').trim(),
    ext: String(item?.ext || '').trim(),
    downloadUrl: String(item?.downloadUrl || '').trim(),
    viewUrl: String(item?.viewUrl || '').trim(),
  })
}

function normalizeArtifactItem(artifact) {
  if (!artifact) return null
  if (typeof artifact === 'string') {
    const raw = artifact.trim()
    if (!raw) return null
    return {
      label: basename(raw),
      name: basename(raw),
      path: raw,
      kind: '',
      ext: raw.includes('.') ? raw.split('.').pop().toLowerCase() : '',
      downloadUrl: '',
      viewUrl: '',
    }
  }
  if (typeof artifact !== 'object') return null
  const path = String(artifact.path || artifact.file_path || '').trim()
  const name = String(artifact.name || artifact.label || '').trim()
  const label = name || basename(path)
  if (!label) return null
  const ext = String(artifact.ext || (label.includes('.') ? label.split('.').pop() : '')).trim().toLowerCase()
  return {
    label,
    name: label,
    path,
    kind: String(artifact.kind || '').trim().toLowerCase(),
    ext,
    downloadUrl: String(artifact.download_url || artifact.downloadUrl || '').trim(),
    viewUrl: String(artifact.view_url || artifact.viewUrl || '').trim(),
  }
}

function extractFileRefs(text) {
  const raw = String(text || '')
  if (!raw) return []
  const matches = raw.match(/(?:[A-Za-z]:)?[A-Za-z0-9._@\-\\/ ]+\.[A-Za-z0-9]{1,8}/g) || []
  const files = []
  for (const match of matches) {
    const rawMatch = match.replace(/^["'`]+|["'`.,:;!?]+$/g, '').trim()
    const cleaned = basename(rawMatch)
    if (!cleaned) continue
    pushUniqueItem(files, {
      label: cleaned,
      path: /[\\/]/.test(rawMatch) || /^[A-Za-z]:/.test(rawMatch) ? rawMatch : '',
    }, 6)
  }
  return files
}

export function normalizeChecklistStatus(value) {
  const status = String(value || '').trim().toLowerCase()
  if (['completed', 'done', 'success', 'ok'].includes(status)) return 'completed'
  if (['running', 'in_progress', 'started', 'active'].includes(status)) return 'running'
  if (['awaiting_approval', 'awaiting_input', 'awaiting'].includes(status)) return 'awaiting'
  if (['failed', 'error'].includes(status)) return 'failed'
  if (['blocked'].includes(status)) return 'blocked'
  if (['skipped'].includes(status)) return 'skipped'
  return status || 'pending'
}

export function extractChecklist(result) {
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

export function isPlanApprovalScope(scope, kind = '', request = null) {
  const joined = [
    scope,
    kind,
    request?.title,
    request?.summary,
    request?.metadata?.approval_mode,
  ].map((value) => String(value || '').toLowerCase()).join(' ')
  return /\bplan\b|project_blueprint|blueprint|deep_research_confirmation/.test(joined)
}

export function isSkillApproval(kind = '', request = null) {
  const approvalMode = String(request?.metadata?.approval_mode || '').trim().toLowerCase()
  const joined = [kind, approvalMode, request?.title].map((value) => String(value || '').toLowerCase()).join(' ')
  return /\bskill_approval\b|skill permission/.test(joined) || approvalMode === 'skill_permission_grant'
}

export function shouldMirrorActivityMessage(msg) {
  if (!msg || msg.role !== 'assistant') return false
  return !!(
    String(msg.runId || '').trim()
    || (Array.isArray(msg.progress) && msg.progress.length)
    || (Array.isArray(msg.checklist) && msg.checklist.length)
    || (Array.isArray(msg.steps) && msg.steps.length)
    || (Array.isArray(msg.artifacts) && msg.artifacts.length)
    || ['thinking', 'streaming', 'awaiting', 'done', 'error'].includes(String(msg.status || '').trim().toLowerCase())
  )
}

export function buildActivityEntry(msg, { id, source = 'studio' } = {}) {
  if (!msg || typeof msg !== 'object') return null
  return {
    id: String(id || msg.id || '').trim(),
    source,
    runId: String(msg.runId || '').trim(),
    mode: String(msg.mode || '').trim(),
    modeLabel: String(msg.modeLabel || '').trim(),
    status: String(msg.status || '').trim(),
    content: String(msg.content || '').trim(),
    progress: Array.isArray(msg.progress) ? msg.progress : [],
    checklist: Array.isArray(msg.checklist) ? msg.checklist : [],
    steps: Array.isArray(msg.steps) ? msg.steps : [],
    artifacts: Array.isArray(msg.artifacts) ? msg.artifacts : [],
    approvalRequest: (msg.approvalRequest && typeof msg.approvalRequest === 'object') ? msg.approvalRequest : null,
    approvalScope: String(msg.approvalScope || '').trim(),
    approvalKind: String(msg.approvalKind || '').trim(),
    approvalState: String(msg.approvalState || '').trim(),
    statusText: String(msg.statusText || '').trim(),
    ts: msg.ts || new Date().toISOString(),
    runStartedAt: msg.runStartedAt || msg.ts || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
}

export function classifyRunActivityKind(item) {
  if (!item || typeof item !== 'object') return 'task'
  const kind = String(item.kind || '').toLowerCase()
  const title = String(item.title || '').toLowerCase()
  const detail = String(item.detail || '').toLowerCase()
  const text = `${kind} ${title} ${detail}`
  if (String(item.command || '').trim()) return 'command'
  if (kind.includes('command') || kind.includes('shell')) return 'command'
  if (/\b(search|query|grep|ripgrep|find in files|look up|browse|web search)\b/.test(text)) return 'search'
  if (/\b(read|open|inspect|scan|inventory|load file|review file|explore file)\b/.test(text)) return 'read'
  if (/\b(edit|write|modify|patch|rewrite|update file|create file|save file|refactor)\b/.test(text)) return 'edit'
  if (/\b(test|verify|review|check|lint)\b/.test(text)) return 'review'
  return 'task'
}

export function summarizeRunArtifacts(progress = [], artifacts = []) {
  const counts = {
    search: 0,
    read: 0,
    edit: 0,
    artifact: 0,
    command: 0,
    review: 0,
  }
  const samples = {
    search: [],
    read: [],
    edit: [],
    artifact: [],
    command: [],
    review: [],
  }

  for (const item of Array.isArray(progress) ? progress : []) {
    const kind = classifyRunActivityKind(item)
    if (counts[kind] !== undefined) counts[kind] += 1
    const candidates = [
      ...extractFileRefs(item.title),
      ...extractFileRefs(item.detail),
      ...extractFileRefs(item.command),
    ]
    for (const candidate of candidates) pushUniqueItem(samples[kind] || [], candidate)
    if (!(samples[kind] || []).length) {
      const fallback = String(item.detail || item.title || item.command || '').trim()
      if (fallback) pushUniqueLabel(samples[kind] || [], fallback, 3)
    }
  }

  const artifactList = [...(Array.isArray(artifacts) ? artifacts : [])].sort((left, right) => {
    const normalize = (item) => normalizeArtifactItem(item) || {}
    const priority = (item) => {
      const normalized = normalize(item)
      const name = String(normalized.name || normalized.label || '').toLowerCase()
      const ext = String(normalized.ext || '').toLowerCase()
      if (/^report\.(pdf|docx|html|md)$/.test(name)) {
        return { pdf: 0, docx: 1, html: 2, md: 3 }[ext] ?? 4
      }
      return 10
    }
    return priority(left) - priority(right)
  })

  const reportItems = []
  for (const artifact of artifactList) {
    const normalized = normalizeArtifactItem(artifact)
    if (!normalized) continue
    counts.artifact += 1
    if (/^report\.(pdf|docx|html|md)$/i.test(String(normalized.name || normalized.label || ''))) {
      pushUniqueItem(reportItems, normalized, 6)
    } else {
      pushUniqueItem(samples.artifact, normalized, 6)
    }
  }

  const makeCard = (kind, title) => ({
    kind,
    title,
    items: samples[kind],
  })

  const cards = []
  const nonReportArtifactCount = Math.max(0, counts.artifact - reportItems.length)
  if (reportItems.length > 0) {
    cards.push({
      kind: 'artifact',
      title: 'Report downloads',
      items: reportItems,
    })
  }
  if (counts.search > 0) cards.push(makeCard('search', `Searched ${counts.search} source${counts.search === 1 ? '' : 's'}`))
  if (counts.read > 0) cards.push(makeCard('read', `Read ${counts.read} file${counts.read === 1 ? '' : 's'}`))
  if (counts.edit > 0) cards.push(makeCard('edit', `Changed ${counts.edit} file${counts.edit === 1 ? '' : 's'}`))
  if (nonReportArtifactCount > 0) cards.push(makeCard('artifact', `Created ${nonReportArtifactCount} artifact${nonReportArtifactCount === 1 ? '' : 's'}`))
  if (counts.command > 0) cards.push(makeCard('command', `Ran ${counts.command} command${counts.command === 1 ? '' : 's'}`))
  if (counts.review > 0) cards.push(makeCard('review', `Checked ${counts.review} task${counts.review === 1 ? '' : 's'}`))
  return cards.slice(0, 4)
}
