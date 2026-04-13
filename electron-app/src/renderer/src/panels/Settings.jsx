import React, { useState, useEffect } from 'react'
import { useApp } from '../contexts/AppContext'

const TABS = [
  { id: 'general',  label: 'General' },
  { id: 'keys',     label: 'API Keys' },
  { id: 'rag',      label: 'RAG & Data' },
  { id: 'models',   label: 'Models' },
  { id: 'editor',   label: 'Editor' },
  { id: 'chat',     label: 'Chat' },
]

export default function Settings() {
  const { state, dispatch } = useApp()
  const [tab, setTab]       = useState('general')
  const [settings, setSettings] = useState({})
  const [saved, setSaved]   = useState(false)
  const [machineStatus, setMachineStatus] = useState(null)
  const [machineStatusLoading, setMachineStatusLoading] = useState(false)
  const api     = window.kendrAPI
  const apiBase = state.backendUrl || 'http://127.0.0.1:2151'
  const providerSettingKeys = ['anthropicKey', 'openaiKey', 'openaiOrgId', 'googleKey', 'xaiKey']

  // Load electron-store settings
  useEffect(() => {
    api?.settings.getAll().then(s => setSettings(s || {}))
  }, [])

  const syncWorkingDirectory = (state.projectRoot || state.settings?.projectRoot || settings.projectRoot || '').trim()

  const fetchMachineStatus = async () => {
    setMachineStatusLoading(true)
    try {
      const q = syncWorkingDirectory ? `?working_directory=${encodeURIComponent(syncWorkingDirectory)}` : ''
      const resp = await fetch(`${apiBase}/api/machine/status${q}`)
      if (!resp.ok) return
      const data = await resp.json().catch(() => ({}))
      const status = data?.status && typeof data.status === 'object' ? data.status : null
      if (status) setMachineStatus(status)
    } catch (_) {
    } finally {
      setMachineStatusLoading(false)
    }
  }

  const refreshMachineSync = async () => {
    setMachineStatusLoading(true)
    try {
      const resp = await fetch(`${apiBase}/api/machine/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope: 'machine',
          working_directory: syncWorkingDirectory || undefined,
        }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) return
      const status = data?.status && typeof data.status === 'object' ? data.status : null
      if (status) setMachineStatus(status)
    } catch (_) {
    } finally {
      setMachineStatusLoading(false)
    }
  }

  useEffect(() => {
    if (tab !== 'general') return
    fetchMachineStatus()
  }, [tab, apiBase, syncWorkingDirectory])

  const update = (key, value) => setSettings(s => ({ ...s, [key]: value }))

  const save = async () => {
    const shouldRestartBackend = providerSettingKeys.some(key => (state.settings?.[key] || '') !== (settings?.[key] || ''))
    for (const [k, v] of Object.entries(settings)) {
      await api?.settings.set(k, v)
    }
    dispatch({ type: 'SET_SETTINGS', settings })
    if (settings.backendUrl)  dispatch({ type: 'SET_BACKEND_URL', url: settings.backendUrl })
    if (settings.projectRoot) dispatch({ type: 'SET_PROJECT_ROOT', root: settings.projectRoot })
    if (shouldRestartBackend && state.backendStatus === 'running') await api?.backend.restart()
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const openFolder = async (key) => {
    const dir = await api?.dialog.openDirectory()
    if (dir) update(key, dir)
  }

  const s = settings

  return (
    <div className="st-root">
      {/* Tab bar */}
      <div className="st-tabs">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`st-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >{t.label}</button>
        ))}
      </div>

      <div className="st-body">
        {/* ── General ── */}
        {tab === 'general' && (
          <>
            <Section title="Backend">
              <Row label="Kendr Root">
                <div className="st-input-row">
                  <input className="st-input" value={s.kendrRoot || ''} onChange={e => update('kendrRoot', e.target.value)} placeholder="auto-detected" />
                  <button className="st-browse" onClick={() => openFolder('kendrRoot')}>…</button>
                </div>
              </Row>
              <Row label="UI Server URL">
                <input className="st-input" value={s.backendUrl || 'http://127.0.0.1:2151'} onChange={e => update('backendUrl', e.target.value)} />
              </Row>
              <Row label="Gateway URL">
                <input className="st-input" value={s.gatewayUrl || 'http://127.0.0.1:8790'} onChange={e => update('gatewayUrl', e.target.value)} />
              </Row>
              <Row label="Python Path">
                <input className="st-input" value={s.pythonPath || ''} onChange={e => update('pythonPath', e.target.value)} placeholder="python" />
              </Row>
              <Row label="Project Root">
                <div className="st-input-row">
                  <input className="st-input" value={s.projectRoot || ''} onChange={e => update('projectRoot', e.target.value)} />
                  <button className="st-browse" onClick={() => openFolder('projectRoot')}>…</button>
                </div>
              </Row>
              <Row label="Auto-start backend">
                <input type="checkbox" className="st-check" checked={!!s.autoStartBackend} onChange={e => update('autoStartBackend', e.target.checked)} />
              </Row>
              <div className="st-actions">
                <button className="st-btn-accent" onClick={() => api?.backend.restart()}>Restart Backend</button>
                <button className="st-btn" onClick={() => api?.backend.stop()}>Stop</button>
              </div>
            </Section>

            <Section title="Git">
              <Row label="Display Name"><input className="st-input" value={s.gitName || ''} onChange={e => update('gitName', e.target.value)} /></Row>
              <Row label="Email"><input className="st-input" value={s.gitEmail || ''} onChange={e => update('gitEmail', e.target.value)} /></Row>
              <Row label="GitHub PAT"><input className="st-input" type="password" value={s.githubPat || ''} onChange={e => update('githubPat', e.target.value)} placeholder="ghp_…" /></Row>
            </Section>

            <Section title="Machine Sync">
              <Row label="Auto Sync Machine Index">
                <input
                  type="checkbox"
                  className="st-check"
                  checked={!!s.machineAutoSyncEnabled}
                  onChange={e => update('machineAutoSyncEnabled', e.target.checked)}
                />
              </Row>
              <Row label="Auto Sync Every (days)">
                <input
                  className="st-input st-input--sm"
                  type="number"
                  min="1"
                  max="30"
                  value={Number(s.machineAutoSyncIntervalDays || 7)}
                  onChange={e => update('machineAutoSyncIntervalDays', Math.max(1, Math.min(30, Number(e.target.value || 7))))}
                />
              </Row>
              <div className="st-actions">
                <button className="st-btn" onClick={refreshMachineSync} disabled={machineStatusLoading}>
                  {machineStatusLoading ? 'Refreshing…' : 'Refresh Machine Index'}
                </button>
              </div>
              <div className="st-info-banner">
                {machineStatus?.software_inventory_last_synced
                  ? `Last machine sync: ${new Date(machineStatus.software_inventory_last_synced).toLocaleString()}`
                  : 'No machine sync snapshot yet. Run machine sync once.'}
              </div>
              <div className="st-machine-apps">
                {(Array.isArray(machineStatus?.discovered_apps) ? machineStatus.discovered_apps : []).length === 0 ? (
                  <div className="st-machine-empty">No discovered apps yet.</div>
                ) : (
                  (machineStatus.discovered_apps || []).map((app) => (
                    <div key={`${app.name}-${app.path || ''}`} className="st-machine-app">
                      <div className="st-machine-app-name">{app.name}</div>
                      <div className="st-machine-app-meta">
                        {app.version || 'version unknown'}
                        {app.path ? ` · ${app.path}` : ''}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </Section>
          </>
        )}

        {/* ── API Keys ── */}
        {tab === 'keys' && (
          <>
            <div className="st-info-banner">
              API keys are stored locally via electron-store and never sent to any server other than the respective provider.
            </div>
            <Section title="Anthropic">
              <Row label="API Key"><input className="st-input" type="password" value={s.anthropicKey || ''} onChange={e => update('anthropicKey', e.target.value)} placeholder="sk-ant-…" /></Row>
            </Section>
            <Section title="OpenAI">
              <Row label="API Key"><input className="st-input" type="password" value={s.openaiKey || ''} onChange={e => update('openaiKey', e.target.value)} placeholder="sk-…" /></Row>
              <Row label="Org ID"><input className="st-input" value={s.openaiOrgId || ''} onChange={e => update('openaiOrgId', e.target.value)} placeholder="org-…" /></Row>
            </Section>
            <Section title="Google AI">
              <Row label="API Key"><input className="st-input" type="password" value={s.googleKey || ''} onChange={e => update('googleKey', e.target.value)} placeholder="AIza…" /></Row>
            </Section>
            <Section title="xAI / Grok">
              <Row label="API Key"><input className="st-input" type="password" value={s.xaiKey || ''} onChange={e => update('xaiKey', e.target.value)} placeholder="xai-…" /></Row>
            </Section>
            <Section title="HuggingFace">
              <Row label="Token"><input className="st-input" type="password" value={s.hfToken || ''} onChange={e => update('hfToken', e.target.value)} placeholder="hf_…" /></Row>
            </Section>
            <Section title="Other">
              <Row label="Tavily (Web Search)"><input className="st-input" type="password" value={s.tavilyKey || ''} onChange={e => update('tavilyKey', e.target.value)} placeholder="tvly-…" /></Row>
              <Row label="Brave Search"><input className="st-input" type="password" value={s.braveKey || ''} onChange={e => update('braveKey', e.target.value)} /></Row>
              <Row label="Serper API"><input className="st-input" type="password" value={s.serperKey || ''} onChange={e => update('serperKey', e.target.value)} /></Row>
            </Section>
          </>
        )}

        {/* ── RAG & Data ── */}
        {tab === 'rag' && (
          <>
            <div className="st-info-banner">
              Configure retrieval-augmented generation (RAG) sources. These are used by research and document agents.
            </div>

            <Section title="Vector Store">
              <Row label="Backend">
                <select className="st-select" value={s.vectorStore || 'chroma'} onChange={e => update('vectorStore', e.target.value)}>
                  <option value="chroma">Chroma (local)</option>
                  <option value="pinecone">Pinecone</option>
                  <option value="weaviate">Weaviate</option>
                  <option value="qdrant">Qdrant</option>
                  <option value="pgvector">pgvector (Postgres)</option>
                </select>
              </Row>
              <Row label="Host / URL">
                <input className="st-input" value={s.vectorStoreUrl || ''} onChange={e => update('vectorStoreUrl', e.target.value)} placeholder="http://localhost:8000" />
              </Row>
              <Row label="API Key">
                <input className="st-input" type="password" value={s.vectorStoreKey || ''} onChange={e => update('vectorStoreKey', e.target.value)} />
              </Row>
              <Row label="Collection / Index">
                <input className="st-input" value={s.vectorCollection || 'kendr_docs'} onChange={e => update('vectorCollection', e.target.value)} />
              </Row>
            </Section>

            <Section title="Embedding Model">
              <Row label="Provider">
                <select className="st-select" value={s.embedProvider || 'openai'} onChange={e => update('embedProvider', e.target.value)}>
                  <option value="openai">OpenAI (text-embedding-3-small)</option>
                  <option value="anthropic">Anthropic (voyage-3)</option>
                  <option value="google">Google (text-embedding-004)</option>
                  <option value="ollama">Ollama (nomic-embed-text)</option>
                  <option value="huggingface">HuggingFace (local)</option>
                </select>
              </Row>
              <Row label="Model Override">
                <input className="st-input" value={s.embedModel || ''} onChange={e => update('embedModel', e.target.value)} placeholder="leave blank for default" />
              </Row>
              <Row label="Dimensions">
                <input className="st-input st-input--sm" type="number" value={s.embedDims || 1536} onChange={e => update('embedDims', +e.target.value)} />
              </Row>
            </Section>

            <Section title="Document Sources">
              <Row label="Local Scan Paths">
                <div className="st-input-row">
                  <input className="st-input" value={s.ragLocalPaths || ''} onChange={e => update('ragLocalPaths', e.target.value)} placeholder="comma-separated folder paths" />
                  <button className="st-browse" onClick={async () => {
                    const dir = await api?.dialog.openDirectory()
                    if (dir) update('ragLocalPaths', s.ragLocalPaths ? `${s.ragLocalPaths},${dir}` : dir)
                  }}>…</button>
                </div>
              </Row>
              <Row label="Chunk Size">
                <input className="st-input st-input--sm" type="number" value={s.ragChunkSize || 512} onChange={e => update('ragChunkSize', +e.target.value)} />
              </Row>
              <Row label="Chunk Overlap">
                <input className="st-input st-input--sm" type="number" value={s.ragChunkOverlap || 64} onChange={e => update('ragChunkOverlap', +e.target.value)} />
              </Row>
              <Row label="Auto-index on start">
                <input type="checkbox" className="st-check" checked={!!s.ragAutoIndex} onChange={e => update('ragAutoIndex', e.target.checked)} />
              </Row>
              <div className="st-actions">
                <button className="st-btn-accent" onClick={async () => {
                  try {
                    await fetch(`${apiBase}/api/rag/index`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths: s.ragLocalPaths?.split(',').map(p => p.trim()).filter(Boolean) }) })
                  } catch {}
                }}>Index Documents Now</button>
              </div>
            </Section>

            <Section title="Web Connectors">
              <Row label="Confluence URL">
                <input className="st-input" value={s.confluenceUrl || ''} onChange={e => update('confluenceUrl', e.target.value)} placeholder="https://company.atlassian.net" />
              </Row>
              <Row label="Confluence Token">
                <input className="st-input" type="password" value={s.confluenceToken || ''} onChange={e => update('confluenceToken', e.target.value)} />
              </Row>
              <Row label="Notion Token">
                <input className="st-input" type="password" value={s.notionToken || ''} onChange={e => update('notionToken', e.target.value)} placeholder="ntn_…" />
              </Row>
              <Row label="SharePoint Tenant">
                <input className="st-input" value={s.sharepointTenant || ''} onChange={e => update('sharepointTenant', e.target.value)} placeholder="tenant.sharepoint.com" />
              </Row>
            </Section>
          </>
        )}

        {/* ── Models ── */}
        {tab === 'models' && (
          <>
            <Section title="Default Model">
              <Row label="Provider">
                <select className="st-select" value={s.defaultProvider || 'auto'} onChange={e => update('defaultProvider', e.target.value)}>
                  <option value="auto">Auto (backend decides)</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                  <option value="google">Google</option>
                  <option value="ollama">Ollama (local)</option>
                </select>
              </Row>
              <Row label="Model ID">
                <input className="st-input" value={s.defaultModel || ''} onChange={e => update('defaultModel', e.target.value)} placeholder="e.g. claude-sonnet-4-6 or llama3.2" />
              </Row>
              <Row label="Temperature">
                <input className="st-input st-input--sm" type="number" min="0" max="2" step="0.1" value={s.temperature ?? 0.7} onChange={e => update('temperature', +e.target.value)} />
              </Row>
              <Row label="Max Tokens">
                <input className="st-input st-input--sm" type="number" value={s.maxTokens || 4096} onChange={e => update('maxTokens', +e.target.value)} />
              </Row>
            </Section>
            <Section title="Ollama">
              <Row label="Model Download Dir">
                <div className="st-input-row">
                  <input className="st-input" value={s.modelDownloadDir || ''} onChange={e => update('modelDownloadDir', e.target.value)} />
                  <button className="st-browse" onClick={() => openFolder('modelDownloadDir')}>…</button>
                </div>
              </Row>
              <Row label="GPU Layers"><input className="st-input st-input--sm" type="number" min="0" value={s.gpuLayers || 0} onChange={e => update('gpuLayers', +e.target.value)} /></Row>
              <Row label="Context Size"><input className="st-input st-input--sm" type="number" value={s.contextSize || 4096} onChange={e => update('contextSize', +e.target.value)} /></Row>
              <Row label="Threads"><input className="st-input st-input--sm" type="number" min="1" max="32" value={s.threads || 4} onChange={e => update('threads', +e.target.value)} /></Row>
            </Section>
          </>
        )}

        {/* ── Editor ── */}
        {tab === 'editor' && (
          <Section title="Editor Preferences">
            <Row label="Font Size"><input className="st-input st-input--sm" type="number" min="10" max="24" value={s.fontSize || 14} onChange={e => update('fontSize', +e.target.value)} /></Row>
            <Row label="Tab Size"><input className="st-input st-input--sm" type="number" min="2" max="8" value={s.tabSize || 2} onChange={e => update('tabSize', +e.target.value)} /></Row>
            <Row label="Font Family"><input className="st-input" value={s.fontFamily || ''} onChange={e => update('fontFamily', e.target.value)} placeholder="'Cascadia Code', monospace" /></Row>
            <Row label="Word Wrap">
              <select className="st-select" value={s.wordWrap || 'off'} onChange={e => update('wordWrap', e.target.value)}>
                <option value="off">Off</option>
                <option value="on">On</option>
                <option value="wordWrapColumn">Column</option>
              </select>
            </Row>
            <Row label="Minimap">
              <input type="checkbox" className="st-check" checked={s.minimap !== false} onChange={e => update('minimap', e.target.checked)} />
            </Row>
            <Row label="Format on Save">
              <input type="checkbox" className="st-check" checked={!!s.formatOnSave} onChange={e => update('formatOnSave', e.target.checked)} />
            </Row>
          </Section>
        )}

        {/* ── Chat ── */}
        {tab === 'chat' && (
          <>
            <Section title="History">
              <Row label="Retention Period">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    className="st-input st-input--sm"
                    type="number"
                    min="0"
                    max="365"
                    value={s.chatHistoryRetentionDays ?? 14}
                    onChange={e => update('chatHistoryRetentionDays', +e.target.value)}
                  />
                  <span className="st-hint">days &nbsp;(0 = keep forever)</span>
                </div>
              </Row>
              <div className="st-info-banner" style={{ marginTop: 8 }}>
                Chat history is stored locally on your device. Conversations older than the
                retention period are automatically deleted when the app loads.
                Default is&nbsp;<strong>14 days</strong>.
              </div>
              <div className="st-actions">
                <button
                  className="st-btn"
                  onClick={() => {
                    if (window.confirm('Delete all chat history? This cannot be undone.')) {
                      localStorage.removeItem('kendr_sessions_v1')
                      localStorage.removeItem('kendr_chat_history_v1')
                    }
                  }}
                >
                  Clear All History
                </button>
              </div>
            </Section>
          </>
        )}
      </div>

      {/* Footer save */}
      <div className="st-footer">
        <button className="st-btn-accent" onClick={save}>
          {saved ? '✓ Saved' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="st-section">
      <div className="st-section-title">{title}</div>
      {children}
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div className="st-row">
      <label className="st-label">{label}</label>
      <div className="st-control">{children}</div>
    </div>
  )
}
