import React, { useEffect, useState } from 'react'
import { useApp } from '../contexts/AppContext'

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  const digits = size >= 10 || unitIndex === 0 ? 0 : 1
  return `${size.toFixed(digits)} ${units[unitIndex]}`
}

export default function ModelManager() {
  const { state } = useApp()
  const [ollamaModels, setOllamaModels] = useState([])
  const [guide, setGuide] = useState(null)
  const [loadingModels, setLoadingModels] = useState(true)
  const [loadingGuide, setLoadingGuide] = useState(true)
  const [pullTag, setPullTag] = useState('')
  const [pullState, setPullState] = useState(null)
  const [pulling, setPulling] = useState(false)
  const [deletingModel, setDeletingModel] = useState('')
  const [pullStatus, setPullStatus] = useState(null)
  const backendUrl = state.backendUrl || 'http://127.0.0.1:2151'

  const fetchModels = async () => {
    setLoadingModels(true)
    try {
      const r = await fetch(`${backendUrl}/api/models/ollama`)
      if (r.ok) {
        const data = await r.json()
        setOllamaModels(Array.isArray(data.models) ? data.models : [])
      }
    } catch (_) {
    } finally {
      setLoadingModels(false)
    }
  }

  const fetchGuide = async (force = false) => {
    setLoadingGuide(true)
    try {
      const suffix = force ? '?refresh=1' : ''
      const r = await fetch(`${backendUrl}/api/models/guide${suffix}`)
      if (r.ok) {
        const data = await r.json()
        setGuide(data || null)
      }
    } catch (_) {
    } finally {
      setLoadingGuide(false)
    }
  }

  const fetchPullStatus = async () => {
    try {
      const r = await fetch(`${backendUrl}/api/models/ollama/pull/status`)
      if (!r.ok) return
      const data = await r.json()
      setPullState(data)
      const live = Boolean(data.active) && ['starting', 'running', 'cancelling'].includes(data.status)
      setPulling(live)
      if (!live && data.status === 'completed') {
        fetchModels()
        fetchGuide(true)
      }
    } catch (_) {}
  }

  useEffect(() => {
    fetchModels()
    fetchGuide(false)
    fetchPullStatus()
  }, [backendUrl])

  useEffect(() => {
    if (!pullState?.active || !['starting', 'running', 'cancelling'].includes(pullState.status)) return
    const timer = setInterval(() => { fetchPullStatus() }, 900)
    return () => clearInterval(timer)
  }, [backendUrl, pullState?.active, pullState?.status])

  useEffect(() => {
    const timer = setInterval(() => { fetchGuide(true) }, 10 * 60 * 1000)
    return () => clearInterval(timer)
  }, [backendUrl])

  const pullModelWithValue = async (modelName) => {
    const model = String(modelName || '').trim()
    if (!model || pulling) return
    setPullTag(model)
    setPullStatus(null)
    try {
      const r = await fetch(`${backendUrl}/api/models/ollama/pull`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
      })
      const data = await r.json().catch(() => ({}))
      if ((r.ok || r.status === 202) && data.ok) {
        setPulling(true)
        setPullState(data.pull || null)
        setPullStatus(null)
        fetchGuide(true)
      } else {
        setPullStatus({ ok: false, msg: data.error || `Pull failed (${r.status})` })
      }
    } catch (e) {
      setPullStatus({ ok: false, msg: `Network error: ${e.message}` })
    }
  }

  const pullModel = async () => {
    await pullModelWithValue(pullTag)
  }

  const cancelPull = async () => {
    try {
      const r = await fetch(`${backendUrl}/api/models/ollama/pull/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      const data = await r.json().catch(() => ({}))
      if (r.ok && data.ok) {
        setPullState(data.pull || null)
        setPulling(Boolean(data.pull?.active))
      } else {
        setPullStatus({ ok: false, msg: data.error || `Cancel failed (${r.status})` })
      }
    } catch (e) {
      setPullStatus({ ok: false, msg: `Network error: ${e.message}` })
    }
  }

  const deleteModel = async (modelName) => {
    const model = String(modelName || '').trim()
    if (!model || deletingModel) return
    setDeletingModel(model)
    setPullStatus(null)
    try {
      const r = await fetch(`${backendUrl}/api/models/ollama/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
      })
      const data = await r.json().catch(() => ({}))
      if (r.ok && data.ok) {
        setPullStatus({ ok: true, msg: `Deleted ${model}` })
        fetchModels()
        fetchGuide(true)
      } else {
        setPullStatus({ ok: false, msg: data.detail || data.error || `Delete failed (${r.status})` })
      }
    } catch (e) {
      setPullStatus({ ok: false, msg: `Network error: ${e.message}` })
    } finally {
      setDeletingModel('')
    }
  }

  const activePull = pullState && (pullState.active || ['completed', 'failed', 'cancelled'].includes(pullState.status)) ? pullState : null
  const progressPercent = Number(activePull?.percent || 0)
  const hasDeterminateProgress = Number(activePull?.total || 0) > 0
  const progressWidth = hasDeterminateProgress ? `${Math.max(0, Math.min(100, progressPercent))}%` : '35%'
  const recommendations = Array.isArray(guide?.recommendations) ? guide.recommendations : []
  const cloudUsage = Array.isArray(guide?.cloud_usage) ? guide.cloud_usage : []
  const rankings = Array.isArray(guide?.openrouter_rankings) ? guide.openrouter_rankings.slice(0, 5) : []

  return (
    <div className="model-manager">
      <div className="sidebar-label">RECOMMENDED NEXT</div>
      {loadingGuide && <div className="sidebar-empty">Building model guide…</div>}
      {!loadingGuide && recommendations.length > 0 && (
        <div className="model-reco-grid">
          {recommendations.slice(0, 6).map(item => {
            const isPulled = item.status === 'pulled'
            const isCloud = item.access === 'cloud'
            return (
              <div key={item.id} className={`model-reco-card ${item.fits_system ? '' : 'model-reco-card--dim'}`}>
                <div className="model-reco-top">
                  <div>
                    <div className="model-reco-name">{item.label}</div>
                    <div className="model-reco-meta">
                      <span className={`model-mini-chip ${isCloud ? 'cloud' : 'local'}`}>{isCloud ? 'cloud' : 'local'}</span>
                      <span className="model-mini-chip">{item.speed}</span>
                      <span className="model-mini-chip">{item.cost}</span>
                    </div>
                  </div>
                  <div className="model-reco-size">{isCloud ? 'No local GB' : `${Number(item.size_gb || 0).toFixed(1)} GB`}</div>
                </div>
                <div className="model-reco-fit">{item.fit_label}</div>
                <div className="model-reco-copy">{Array.isArray(item.best_for) ? item.best_for.join(' • ') : ''}</div>
                <div className="model-reco-copy">{Array.isArray(item.agent_fit) ? `Agents: ${item.agent_fit.join(' • ')}` : ''}</div>
                <div className="model-reco-note">{item.notes}</div>
                <div className="model-reco-actions">
                  <button className="btn-accent" disabled={pulling || isPulled} onClick={() => pullModelWithValue(item.id)}>
                    {isPulled ? 'Pulled' : isCloud ? 'Add Alias' : 'Pull'}
                  </button>
                  {isPulled && (
                    <button className="btn-danger" disabled={deletingModel === item.id} onClick={() => deleteModel(item.id)}>
                      {deletingModel === item.id ? 'Deleting…' : 'Delete'}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="sidebar-label">OLLAMA MODELS</div>

      <div className="model-pull-row">
        <input
          className="model-input"
          placeholder="e.g. llama3.2, mistral, deepseek-r1, kimi-k2.5:cloud"
          value={pullTag}
          onChange={e => { setPullTag(e.target.value); setPullStatus(null) }}
          onKeyDown={e => e.key === 'Enter' && pullModel()}
          disabled={pulling}
        />
        {!pulling && (
          <button className="btn-accent" disabled={!pullTag.trim()} onClick={pullModel}>
            Pull
          </button>
        )}
        {pulling && (
          <button className="btn-danger" onClick={cancelPull}>
            Cancel
          </button>
        )}
      </div>

      {activePull && activePull.status !== 'idle' && (
        <>
          <div className="model-pull-progress">
            {activePull.message || `Downloading ${activePull.model} — this may take a few minutes…`}
          </div>
          <div className="model-download-card" aria-live="polite">
            <div className="model-download-row">
              <span className="model-name">{activePull.model}</span>
              <span className="model-download-status">
                {activePull.status === 'completed' && 'Completed'}
                {activePull.status === 'failed' && 'Failed'}
                {activePull.status === 'cancelled' && 'Cancelled'}
                {activePull.status === 'cancelling' && 'Cancelling…'}
                {['starting', 'running'].includes(activePull.status) && `${progressPercent.toFixed(1)}%`}
              </span>
            </div>
            <div className="model-download-meta">
              <span>{formatBytes(activePull.completed)} downloaded</span>
              <span>{hasDeterminateProgress ? `${formatBytes(activePull.total)} total` : 'Calculating size…'}</span>
            </div>
            <div className={`model-download-bar ${hasDeterminateProgress ? '' : 'indeterminate'}`} role="progressbar" aria-label={`Downloading ${activePull.model}`} aria-valuemin={0} aria-valuemax={hasDeterminateProgress ? Number(activePull.total || 0) : 100} aria-valuenow={hasDeterminateProgress ? Number(activePull.completed || 0) : undefined}>
              <div className="model-download-bar-fill" style={{ width: progressWidth }} />
            </div>
            {activePull.digest && (
              <div className="model-download-detail">Layer: {activePull.digest}</div>
            )}
            {activePull.error && (
              <div className="model-download-error">{activePull.error}</div>
            )}
          </div>
        </>
      )}

      {pullStatus && (
        <div className={`model-pull-result ${pullStatus.ok ? 'model-pull-result--ok' : 'model-pull-result--err'}`}>
          {pullStatus.msg}
        </div>
      )}

      {loadingModels && !pulling && (
        <div className="sidebar-empty">Checking Ollama models…</div>
      )}
      {!loadingModels && ollamaModels.length === 0 && !pulling && (
        <div className="sidebar-empty">No Ollama models found. Pull one above or start Ollama.</div>
      )}
      {!loadingModels && ollamaModels.map(m => {
        const name = m.name || m
        const isCloud = String(name).includes(':cloud')
        return (
          <div key={name} className="model-item">
            <div className="model-item-main">
              <span className="model-name">{name}</span>
              <span className={`model-mini-chip ${isCloud ? 'cloud' : 'local'}`}>{isCloud ? 'cloud alias' : 'local'}</span>
            </div>
            <div className="model-item-actions">
              <span className="model-size">{m.size ? `${(m.size / 1e9).toFixed(1)} GB` : ''}</span>
              <button className="btn-danger" disabled={deletingModel === name} onClick={() => deleteModel(name)}>
                {deletingModel === name ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        )
      })}

      {cloudUsage.length > 0 && (
        <>
          <div className="sidebar-label" style={{ marginTop: 16 }}>CLOUD MODELS</div>
          <div className="model-cloud-guide">
            {cloudUsage.map(item => (
              <div key={item.title} className="model-cloud-card">
                <div className="model-cloud-title">{item.title}</div>
                <div className="model-cloud-body">{item.body}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {rankings.length > 0 && (
        <>
          <div className="sidebar-label" style={{ marginTop: 16 }}>OPENROUTER TOP</div>
          <div className="model-ranking-list">
            {rankings.map(item => (
              <div key={`${item.rank}:${item.name}`} className="model-ranking-row">
                <span className="model-ranking-rank">#{item.rank}</span>
                <span className="model-ranking-name">{item.name}</span>
                <span className="model-ranking-meta">{item.tokens} • {item.share}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="sidebar-label" style={{ marginTop: 16 }}>CONFIGURED PROVIDERS</div>
      <div className="model-providers">
        {['openai', 'anthropic', 'google', 'ollama'].map(p => (
          <div key={p} className="provider-row">
            <span className="provider-name">{p}</span>
            <span className="provider-badge">via kendr setup</span>
          </div>
        ))}
      </div>
    </div>
  )
}
