import React, { useCallback, useEffect, useState } from 'react'
import { useApp } from '../contexts/AppContext'

export default function MachineHub() {
  const { state } = useApp()
  const apiBase = state.backendUrl || 'http://127.0.0.1:2151'
  const workingDirectory = (state.projectRoot || state.settings?.projectRoot || '').trim()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchDetails = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const q = new URLSearchParams()
      if (workingDirectory) q.set('working_directory', workingDirectory)
      q.set('max_files', '20000')
      const resp = await fetch(`${apiBase}/api/machine/details?${q.toString()}`)
      const body = await resp.json().catch(() => ({}))
      if (!resp.ok) throw new Error(body?.error || `machine_${resp.status}`)
      setData(body || null)
    } catch (err) {
      setError(String(err?.message || err || 'Failed to load machine details'))
    } finally {
      setLoading(false)
    }
  }, [apiBase, workingDirectory])

  useEffect(() => {
    fetchDetails()
  }, [fetchDetails])

  const apps = Array.isArray(data?.apps) ? data.apps : []
  const status = data?.status || {}
  const system = data?.system_info || status?.system_info || {}

  return (
    <div className="kendr-page machine-page">
      <section className="hero-card machine-hero">
        <div className="hero-copy">
          <span className="eyebrow">Machine</span>
          <h1>See machine facts and available apps.</h1>
          <p>Keep this view focused on system snapshot and synced software inventory.</p>
          <div className="hero-actions">
            <button className="kendr-btn kendr-btn--primary" onClick={fetchDetails} disabled={loading}>
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
          {error && <div className="machine-error">{error}</div>}
          <div className="machine-note">Workspace root: {system.workspace_root || data?.working_directory || 'unknown'}</div>
        </div>
        <div className="hero-metrics">
          <MetricCard label="Apps" value={String(Number(status?.installed_software_count || 0))} detail="Installed tools in snapshot" />
          <MetricCard label="Host" value={system.hostname || 'unknown'} detail={system.architecture || 'unknown'} />
          <MetricCard label="Memory" value={system.total_memory_gb ? `${system.total_memory_gb} GB` : 'unknown'} detail={system.python_version ? `Python ${system.python_version}` : 'Python unknown'} />
        </div>
      </section>

      <section className="grid-two machine-grid">
        <div className="surface-card machine-card">
          <SectionHeader title="System Snapshot" subtitle="Machine-wide environment facts" />
          <div className="machine-kv-grid">
            <KeyValue label="Host" value={system.hostname || 'unknown'} />
            <KeyValue label="OS" value={[system.os, system.os_release].filter(Boolean).join(' ') || system.platform || 'unknown'} />
            <KeyValue label="Arch" value={system.architecture || 'unknown'} />
            <KeyValue label="Python" value={system.python_version || 'unknown'} />
            <KeyValue label="CPU Cores" value={String(system.cpu_count || 0)} />
            <KeyValue label="Memory" value={system.total_memory_gb ? `${system.total_memory_gb} GB` : 'unknown'} />
            <KeyValue label="Disk Root" value={system.disk_root || 'unknown'} />
            <KeyValue label="Disk Free" value={system.disk_free_gb ? `${system.disk_free_gb} GB` : 'unknown'} />
          </div>
        </div>

        <div className="surface-card machine-card">
          <SectionHeader title="Synced Apps" subtitle="Software inventory snapshot" />
          {apps.length === 0 ? (
            <div className="empty-state"><div className="empty-state__title">No apps synced yet</div><div className="empty-state__body">Run machine sync first.</div></div>
          ) : (
            <div className="machine-app-list machine-app-list--scroll">
              {apps.map((app) => (
                <div className="machine-app-row" key={`${app.name}-${app.path || ''}`}>
                  <div>
                    <div className="machine-app-row__name">{app.name}</div>
                    <div className="machine-app-row__meta">{app.version || 'version unknown'}</div>
                  </div>
                  <div className="machine-app-row__path" title={app.path || ''}>{app.path || 'path unknown'}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function SectionHeader({ title, subtitle }) {
  return <div className="section-header"><div><h2>{title}</h2><p>{subtitle}</p></div></div>
}

function MetricCard({ label, value, detail }) {
  return <div className="metric-card"><span className="metric-card__label">{label}</span><span className="metric-card__value">{value}</span><span className="metric-card__detail">{detail}</span></div>
}

function KeyValue({ label, value }) {
  return (
    <div className="machine-kv">
      <span className="machine-kv__label">{label}</span>
      <span className="machine-kv__value" title={value}>{value}</span>
    </div>
  )
}
