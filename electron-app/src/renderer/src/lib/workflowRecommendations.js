function normalizeStageRow(stage) {
  if (!stage || typeof stage !== 'object' || Array.isArray(stage)) return null
  return {
    stage: String(stage.stage || '').trim(),
    label: String(stage.label || '').trim(),
    provider: String(stage.provider || '').trim(),
    model: String(stage.model || '').trim(),
    reason: String(stage.reason || '').trim(),
  }
}

function normalizeStageCandidate(candidate) {
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return null
  const provider = String(candidate.provider || '').trim()
  const model = String(candidate.model || '').trim()
  if (!provider || !model) return null
  return {
    stage: String(candidate.stage || '').trim(),
    label: String(candidate.label || '').trim(),
    provider,
    model,
    value: `${provider}/${model}`,
    labelFull: String(candidate.label_full || '').trim(),
    reason: String(candidate.reason || '').trim(),
    costBand: String(candidate.cost_band || candidate.costBand || 'unknown').trim() || 'unknown',
    qualityScore: Number(candidate.quality_score || candidate.qualityScore || 0) || 0,
  }
}

export function normalizeWorkflowCombo(combo) {
  if (!combo || typeof combo !== 'object' || Array.isArray(combo)) {
    return {
      available: false,
      summary: '',
      estimatedCostBand: 'unknown',
      estimated_cost_band: 'unknown',
      stages: [],
    }
  }
  const estimatedCostBand = String(combo.estimated_cost_band || combo.estimatedCostBand || 'unknown').trim() || 'unknown'
  return {
    available: Boolean(combo.available),
    summary: String(combo.summary || '').trim(),
    estimatedCostBand,
    estimated_cost_band: estimatedCostBand,
    stages: Array.isArray(combo.stages)
      ? combo.stages.map(normalizeStageRow).filter(Boolean)
      : [],
  }
}

export function normalizeWorkflowStageOptions(stageOptions) {
  const raw = Array.isArray(stageOptions) ? stageOptions : []
  return raw
    .map((stageOption) => {
      if (!stageOption || typeof stageOption !== 'object' || Array.isArray(stageOption)) return null
      return {
        stage: String(stageOption.stage || '').trim(),
        label: String(stageOption.label || '').trim(),
        candidates: Array.isArray(stageOption.candidates)
          ? stageOption.candidates.map(normalizeStageCandidate).filter(Boolean)
          : [],
      }
    })
    .filter(Boolean)
}

export function resolveWorkflowRecommendation(modelInventory, workflowId) {
  const normalizedId = String(workflowId || '').trim()
  if (!normalizedId) return null
  const payload = modelInventory?.workflow_recommendations
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null

  const workflowList = Array.isArray(payload.workflows)
    ? payload.workflows
    : (
      payload.workflows && typeof payload.workflows === 'object' && !Array.isArray(payload.workflows)
        ? Object.values(payload.workflows)
        : []
    )

  const directMatch = workflowList.find((item) => (
    item && typeof item === 'object' && !Array.isArray(item) && String(item.id || '').trim() === normalizedId
  ))
  if (directMatch) return directMatch

  const legacyEntry = payload[normalizedId]
  if (legacyEntry && typeof legacyEntry === 'object' && !Array.isArray(legacyEntry)) {
    return {
      id: normalizedId,
      ...legacyEntry,
    }
  }
  return null
}
