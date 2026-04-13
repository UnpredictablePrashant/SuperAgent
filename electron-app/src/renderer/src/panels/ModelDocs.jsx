import React, { useEffect, useMemo, useState } from 'react'
import { useApp } from '../contexts/AppContext'

const capabilityLabel = (value) => (value ? 'Yes' : 'No')

function priceLabel(value) {
  if (value == null) return '—'
  if (value === 0) return 'Free'
  return `$${Number(value).toFixed(2)}/M`
}

export default function ModelDocs() {
  const { state, refreshModelInventory } = useApp()
  const apiBase = state.backendUrl || 'http://127.0.0.1:2151'
  const inventory = state.modelInventory
  const loadingInventory = !!state.modelInventoryLoading && !inventory
  const inventoryError = !!state.modelInventoryError
  const [guide, setGuide] = useState(null)
  const [loadingGuide, setLoadingGuide] = useState(false)
  const [guideError, setGuideError] = useState('')

  const loadGuide = async (force = false) => {
    setLoadingGuide(true)
    setGuideError('')
    try {
      const suffix = force ? '?refresh=1' : ''
      const r = await fetch(`${apiBase}/api/models/guide${suffix}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setGuide(data || null)
    } catch (err) {
      setGuideError(err?.message || 'Failed to load model guide')
    } finally {
      setLoadingGuide(false)
    }
  }

  useEffect(() => {
    refreshModelInventory(false)
    loadGuide(false)
  }, [apiBase, refreshModelInventory])

  useEffect(() => {
    const timer = setInterval(() => { loadGuide(true) }, 10 * 60 * 1000)
    return () => clearInterval(timer)
  }, [apiBase])

  const rows = useMemo(() => {
    const providers = Array.isArray(inventory?.providers) ? inventory.providers : []
    return providers.filter(provider => provider.has_key || provider.provider === 'ollama')
  }, [inventory])

  const recommendations = Array.isArray(guide?.recommendations) ? guide.recommendations : []
  const comparison = Array.isArray(guide?.openrouter_comparison) ? guide.openrouter_comparison : []
  const rankings = Array.isArray(guide?.openrouter_rankings) ? guide.openrouter_rankings : []
  const cloudUsage = Array.isArray(guide?.cloud_usage) ? guide.cloud_usage : []
  const generatedAt = guide?.generated_at ? new Date(guide.generated_at).toLocaleString() : ''

  return (
    <div className="md-root">
      <div className="md-hero">
        <div>
          <div className="md-eyebrow">Reference</div>
          <h2 className="md-title">Model Decision Hub</h2>
          <p className="md-subtitle">
            Fast local guide first, live provider inventory second. Pull recommendations use machine RAM, Ollama inventory, and OpenRouter ranking signals.
          </p>
        </div>
        <div className="md-hero-actions">
          {generatedAt && <div className="md-updated">Updated {generatedAt}</div>}
          <button className="md-refresh" onClick={() => { refreshModelInventory(true); loadGuide(true) }}>Reload</button>
        </div>
      </div>

      {(loadingGuide || loadingInventory) && <div className="md-state">Loading model knowledge…</div>}
      {!loadingGuide && guideError && <div className="md-state md-state--error">{guideError}</div>}

      {recommendations.length > 0 && (
        <section className="md-section">
          <div className="md-section-head">
            <h3 className="md-section-title">What To Pull</h3>
            <div className="md-section-copy">
              Machine RAM: {guide?.system_memory_gb ? `${guide.system_memory_gb} GB detected` : 'unknown'}
            </div>
          </div>
          <div className="md-card-grid">
            {recommendations.map(item => (
              <article key={item.id} className={`md-card ${item.fits_system ? '' : 'md-card--dim'}`}>
                <div className="md-card-top">
                  <div>
                    <div className="md-card-title">{item.label}</div>
                    <div className="md-model-cell">
                      <span className={`md-chip ${item.access === 'cloud' ? 'latest' : 'cheapest'}`}>{item.access}</span>
                      <span className="md-chip best">{item.speed}</span>
                      <span className="md-chip">{item.cost}</span>
                    </div>
                  </div>
                  <div className="md-card-side">{item.access === 'cloud' ? 'No local GB' : `${Number(item.size_gb || 0).toFixed(1)} GB`}</div>
                </div>
                <div className="md-card-fit">{item.fit_label}</div>
                <div className="md-card-line">{Array.isArray(item.best_for) ? item.best_for.join(' • ') : ''}</div>
                <div className="md-card-line">{Array.isArray(item.agent_fit) ? `Agents: ${item.agent_fit.join(' • ')}` : ''}</div>
                <div className="md-card-note">{item.notes}</div>
              </article>
            ))}
          </div>
        </section>
      )}

      {cloudUsage.length > 0 && (
        <section className="md-section">
          <div className="md-section-head">
            <h3 className="md-section-title">Cloud Aliases In Ollama</h3>
            <div className="md-section-copy">How `:cloud` models like Kimi and GLM work.</div>
          </div>
          <div className="md-info-grid">
            {cloudUsage.map(item => (
              <article key={item.title} className="md-info-card">
                <div className="md-info-title">{item.title}</div>
                <div className="md-info-copy">{item.body}</div>
              </article>
            ))}
          </div>
        </section>
      )}

      {comparison.length > 0 && (
        <section className="md-section">
          <div className="md-section-head">
            <h3 className="md-section-title">Cloud Comparison</h3>
            <div className="md-section-copy">Live-ish OpenRouter model metadata for speed/cost/context tradeoffs.</div>
          </div>
          <div className="md-table-wrap">
            <table className="md-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Context</th>
                  <th>Prompt</th>
                  <th>Completion</th>
                  <th>Price Band</th>
                  <th>Tools</th>
                  <th>Vision</th>
                  <th>Structured</th>
                </tr>
              </thead>
              <tbody>
                {comparison.map(item => (
                  <tr key={item.id}>
                    <td>{item.name}</td>
                    <td>{item.context_length ? `${Number(item.context_length).toLocaleString()} tok` : '—'}</td>
                    <td>{priceLabel(item.prompt_price_per_million)}</td>
                    <td>{priceLabel(item.completion_price_per_million)}</td>
                    <td>{item.price_band || '—'}</td>
                    <td>{capabilityLabel(item.supports_tools)}</td>
                    <td>{capabilityLabel(item.supports_vision)}</td>
                    <td>{capabilityLabel(item.supports_structured_output)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {rankings.length > 0 && (
        <section className="md-section">
          <div className="md-section-head">
            <h3 className="md-section-title">OpenRouter Ranking Pulse</h3>
            <div className="md-section-copy">
              Source: {guide?.rankings_source === 'live' ? 'live page' : 'fallback snapshot'}
            </div>
          </div>
          <div className="md-ranking-grid">
            {rankings.slice(0, 10).map(item => (
              <article key={`${item.rank}:${item.name}`} className="md-ranking-card">
                <div className="md-ranking-top">
                  <span className="md-ranking-rank">#{item.rank}</span>
                  <span className="md-ranking-share">{item.share}</span>
                </div>
                <div className="md-ranking-name">{item.name}</div>
                <div className="md-ranking-author">{item.author}</div>
                <div className="md-ranking-tokens">{item.tokens} weekly tokens</div>
              </article>
            ))}
          </div>
        </section>
      )}

      {!loadingInventory && inventoryError && (
        <div className="md-state md-state--error">Provider inventory slow/offline. Guide still loaded.</div>
      )}

      {!loadingInventory && !inventoryError && rows.length === 0 && (
        <div className="md-state">No configured providers yet. Add a model API key in Settings to populate provider comparison.</div>
      )}

      {!loadingInventory && !inventoryError && rows.length > 0 && (
        <section className="md-section">
          <div className="md-section-head">
            <h3 className="md-section-title">Configured Providers</h3>
            <div className="md-section-copy">Live capability hints for models currently wired into Kendr.</div>
          </div>
          <div className="md-table-wrap">
            <table className="md-table">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Configured Model</th>
                  <th>Status</th>
                  <th>Context</th>
                  <th>Tool Calling</th>
                  <th>Agent Capable</th>
                  <th>Vision</th>
                  <th>Structured Output</th>
                  <th>Reasoning</th>
                  <th>Suggested Latest</th>
                  <th>Suggested Best</th>
                  <th>Suggested Cheapest</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((provider) => {
                  const badges = provider.model_badges || {}
                  const latest = Object.keys(badges).find(model => badges[model]?.includes('latest')) || '—'
                  const best = Object.keys(badges).find(model => badges[model]?.includes('best')) || '—'
                  const cheapest = Object.keys(badges).find(model => badges[model]?.includes('cheapest')) || '—'
                  const capabilities = provider.model_capabilities || {}
                  const status = provider.model_fetch_error
                    ? `Error: ${provider.model_fetch_error}`
                    : provider.ready
                      ? 'Ready'
                      : provider.note || 'Not ready'

                  return (
                    <tr key={provider.provider}>
                      <td>{provider.provider}</td>
                      <td>
                        <div className="md-model-cell">
                          <span>{provider.model || '—'}</span>
                          {provider.model_badges?.[provider.model]?.map(badge => (
                            <span key={`${provider.provider}:${provider.model}:${badge}`} className={`md-chip ${badge}`}>{badge}</span>
                          ))}
                        </div>
                      </td>
                      <td className={provider.model_fetch_error ? 'md-error-text' : ''}>{status}</td>
                      <td>{provider.context_window ? `${provider.context_window.toLocaleString()} tokens` : '—'}</td>
                      <td>{capabilityLabel(capabilities.tool_calling)}</td>
                      <td>{capabilityLabel(provider.agent_capable)}</td>
                      <td>{capabilityLabel(capabilities.vision)}</td>
                      <td>{capabilityLabel(capabilities.structured_output)}</td>
                      <td>{capabilityLabel(capabilities.reasoning)}</td>
                      <td>{latest}</td>
                      <td>{best}</td>
                      <td>{cheapest}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
