export function resolveSelectedModel(selectedModel) {
  const raw = String(selectedModel || '').trim()
  if (!raw) {
    return { raw: '', provider: '', model: '', isLocal: false, label: 'Auto' }
  }

  const slash = raw.indexOf('/')
  if (slash === -1) {
    return {
      raw,
      provider: '',
      model: raw,
      isLocal: false,
      label: raw,
    }
  }

  const provider = raw.slice(0, slash).trim().toLowerCase()
  const model = raw.slice(slash + 1).trim()
  const providerLabel = provider === 'ollama'
    ? 'Local'
    : provider
      ? provider.charAt(0).toUpperCase() + provider.slice(1)
      : 'Model'

  return {
    raw,
    provider,
    model,
    isLocal: provider === 'ollama',
    label: `${providerLabel} · ${model || 'default'}`,
  }
}

const MODEL_CONTEXT_WINDOWS = [
  ['gpt-5.4', 400000],
  ['gpt-5.3', 400000],
  ['gpt-5.2', 400000],
  ['gpt-5.1', 400000],
  ['gpt-5-mini', 400000],
  ['gpt-5-nano', 400000],
  ['gpt-5', 400000],
  ['gpt-4.1', 1047576],
  ['o4-mini', 200000],
  ['o3', 200000],
  ['o1', 200000],
  ['gpt-4o', 128000],
  ['gpt-4-turbo', 128000],
  ['gpt-4', 8192],
  ['gpt-3.5', 16385],
  ['claude-sonnet-4', 200000],
  ['claude-opus-4', 200000],
  ['claude', 200000],
  ['gemini-2.5-pro', 1048576],
  ['gemini-2.5-flash', 1048576],
  ['gemini-2.0-flash', 1048576],
  ['gemini-1.5-pro', 2097152],
  ['gemini-1.5-flash', 1048576],
  ['gemini', 1048576],
  ['grok-4.20', 2000000],
  ['grok-4', 2000000],
  ['grok', 131072],
  ['llama3', 131072],
  ['llama', 131072],
  ['mistral', 32768],
  ['phi', 131072],
  ['qwen', 131072],
  ['glm', 131072],
  ['minimax', 1000000],
]

export function approximateContextWindow(model) {
  const normalized = String(model || '').trim().toLowerCase()
  if (!normalized) return 128000
  for (const [needle, limit] of MODEL_CONTEXT_WINDOWS) {
    if (normalized.includes(needle)) return limit
  }
  return 128000
}

export function resolveContextWindow(selectedModel, modelInventory) {
  const selected = resolveSelectedModel(selectedModel)
  const providers = Array.isArray(modelInventory?.providers) ? modelInventory.providers : []
  if (selected.provider && selected.model) {
    const matched = providers.find((provider) => (
      String(provider?.provider || '').trim().toLowerCase() === selected.provider
      && String(provider?.model || '').trim() === selected.model
      && Number(provider?.context_window || 0) > 0
    ))
    if (matched) return Number(matched.context_window)
    return approximateContextWindow(selected.model)
  }
  return Number(modelInventory?.active_context_window || modelInventory?.context_window || 128000) || 128000
}

export function resolveAgentCapability(selectedModel, modelInventory) {
  const selected = resolveSelectedModel(selectedModel)
  if (!selected.provider || !selected.model) return true
  const providers = Array.isArray(modelInventory?.providers) ? modelInventory.providers : []
  const provider = providers.find((item) => String(item?.provider || '').trim().toLowerCase() === selected.provider)
  const details = Array.isArray(provider?.selectable_model_details) ? provider.selectable_model_details : []
  const matched = details.find((item) => String(item?.name || '').trim() === selected.model)
  if (matched && typeof matched.agent_capable === 'boolean') return matched.agent_capable
  if (typeof provider?.agent_capable === 'boolean' && String(provider?.model || '').trim() === selected.model) return provider.agent_capable
  return selected.provider !== 'ollama'
}

export function basename(path) {
  return String(path || '').split(/[\\/]/).pop() || ''
}
