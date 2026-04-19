import React from 'react'
import { useApp } from '../contexts/AppContext'

function formatCheckedAt(value) {
  if (!value) return 'Not checked yet'
  const ts = new Date(value)
  if (Number.isNaN(ts.getTime())) return 'Not checked yet'
  return ts.toLocaleString()
}

function updateFeedLabel(updateStatus) {
  if (updateStatus.feedUrl) return updateStatus.feedUrl
  if (updateStatus.feedSource === 'packaged') return 'Packaged release feed'
  return 'Not configured'
}

export default function AboutPanel() {
  const api = window.kendrAPI
  const { state } = useApp()
  const updateStatus = state.updateStatus || {}
  const currentVersion = updateStatus.currentVersion || 'unknown'
  const targetVersion = updateStatus.downloadedVersion || updateStatus.availableVersion || currentVersion
  const downloading = updateStatus.status === 'downloading'
  const checking = updateStatus.status === 'checking'

  return (
    <div className="kendr-page kendr-about">
      <section className="hero-card kendr-about-hero">
        <div className="hero-copy">
          <span className="eyebrow">About Kendr</span>
          <h1>Kendr is an execution workspace for research, planning, and agent-driven work.</h1>
          <p>
            Instead of treating AI like a single chat box, Kendr gives you one surface for deep research,
            model routing, local file search, multi-step plans, workflow execution, and persistent run history.
            It is designed to move from a question to a real outcome.
          </p>
          <div className="hero-actions">
            <button className="kendr-btn kendr-btn--primary" onClick={() => api?.shell?.openExternal('https://kendr.org')}>
              Visit kendr.org
            </button>
          </div>
        </div>
        <div className="hero-metrics">
          <MetricCard label="Primary role" value="Research to execution" detail="One workspace across discovery, planning, and delivery." />
          <MetricCard label="Core interaction" value="Prompt + workflow" detail="Start in search, branch into plan, agent, or deep research." />
          <MetricCard label="Built for" value="Real tasks" detail="Files, systems, tools, runs, and inspectable outputs." />
        </div>
      </section>

      <section className="grid-two">
        <div className="surface-card">
          <SectionHeader title="What Kendr Does" subtitle="A practical view of the product." />
          <AboutList
            items={[
              'Deep research with structured settings, citations, and source controls.',
              'Model routing across cloud and local models from the same workspace.',
              'Agent and plan modes for multi-step tasks that go beyond a single reply.',
              'Connections to files, MCP tools, integrations, and execution traces.',
              'A persistent shell where research, runs, and settings stay connected.',
            ]}
          />
        </div>

        <div className="surface-card">
          <SectionHeader title="Why It Exists" subtitle="The product intent behind Kendr." />
          <p className="kendr-about-copy">
            Kendr is built around the idea that useful AI products should not stop at text generation.
            They should help users investigate, plan, act, inspect what happened, and continue from there.
            The goal is to turn fragmented AI interactions into a coherent working environment.
          </p>
        </div>
      </section>

      <section className="surface-card">
        <SectionHeader title="Core Surfaces" subtitle="The main ways Kendr is meant to be used." />
        <div className="about-grid">
          <AboutCard
            title="Studio"
            body="A focused orchestration surface for search-first work, research flows, planning, and model selection."
          />
          <AboutCard
            title="Build"
            body="Automation, builders, and higher-level product assembly surfaces."
          />
          <AboutCard
            title="Integrations"
            body="Connect external systems, MCP servers, and tools that agents can use."
          />
          <AboutCard
            title="Runs"
            body="Inspect execution history, workflow status, and traceable agent output."
          />
          <AboutCard
            title="Memory"
            body="Keep relevant context, project state, and reusable information close to execution."
          />
          <AboutCard
            title="Settings"
            body="Control providers, models, local engines, and environment-level behavior."
          />
        </div>
      </section>

      <section className="surface-card">
        <SectionHeader title="Creator" subtitle="Project attribution." />
        <div className="about-creator">
          <div className="about-creator-name">Prashant Dey</div>
          <div className="about-creator-copy">
            Creator of Kendr. The project website is <button className="kendr-inline-link" onClick={() => api?.shell?.openExternal('https://kendr.org')}>kendr.org</button>.
          </div>
        </div>
      </section>

      <section className="surface-card">
        <SectionHeader title="Desktop Updates" subtitle="Remote application delivery for installed users." />
        <div className="about-grid">
          <AboutCard
            title="Current Version"
            body={currentVersion}
          />
          <AboutCard
            title="Update Status"
            body={updateStatus.message || 'Update status unavailable.'}
          />
          <AboutCard
            title="Release Feed"
            body={updateFeedLabel(updateStatus)}
          />
        </div>
        <p className="kendr-about-copy">
          {`Target version: ${targetVersion} · Last check: ${formatCheckedAt(updateStatus.checkedAt)}`}
        </p>
        <div className="hero-actions">
          <button className="kendr-btn kendr-btn--primary" onClick={() => api?.updates?.check()} disabled={checking}>
            {checking ? 'Checking…' : 'Check for Updates'}
          </button>
          {updateStatus.status === 'available' && updateStatus.autoDownload === false && (
            <button className="kendr-btn" onClick={() => api?.updates?.download()}>
              Download Update
            </button>
          )}
          {updateStatus.status === 'downloaded' && (
            <button className="kendr-btn" onClick={() => api?.updates?.install()}>
              Restart to Update
            </button>
          )}
          {downloading && (
            <button className="kendr-btn" disabled>
              Downloading…
            </button>
          )}
        </div>
      </section>
    </div>
  )
}

function SectionHeader({ title, subtitle }) {
  return (
    <div className="section-header">
      <div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
    </div>
  )
}

function MetricCard({ label, value, detail }) {
  return (
    <div className="metric-card">
      <span className="metric-card__label">{label}</span>
      <span className="metric-card__value">{value}</span>
      <span className="metric-card__detail">{detail}</span>
    </div>
  )
}

function AboutCard({ title, body }) {
  return (
    <div className="about-card">
      <div className="about-card__title">{title}</div>
      <div className="about-card__body">{body}</div>
    </div>
  )
}

function AboutList({ items }) {
  return (
    <div className="about-list">
      {items.map((item) => (
        <div key={item} className="about-list__item">
          <span className="about-list__dot" />
          <span>{item}</span>
        </div>
      ))}
    </div>
  )
}
