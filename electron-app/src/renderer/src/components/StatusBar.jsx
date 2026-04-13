import React, { useState, useEffect } from 'react'
import { useApp } from '../contexts/AppContext'

const DOT = { running: '●', starting: '◌', error: '✕', stopped: '○', connecting: '◌' }
const CLS = { running: 'svc-ok', starting: 'svc-warn', error: 'svc-error', stopped: 'svc-muted', connecting: 'svc-warn' }

export default function StatusBar() {
  const { state, dispatch } = useApp()
  const [time, setTime] = useState(new Date())
  const api = window.kendrAPI

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 30000)
    return () => clearInterval(id)
  }, [])

  const { ui, gateway, pid, error } = state.backendServices
  const activeTab = state.openTabs.find(t => t.path === state.activeTabPath)
  const activeRunId = String(state.activeRunId || '').trim()
  const runLabel = activeRunId ? activeRunId.slice(-8) : ''

  const handleServiceClick = async () => {
    if (ui === 'running' && gateway === 'running') return
    if (ui === 'stopped' || gateway === 'stopped' || ui === 'error' || gateway === 'error') {
      await api?.backend.start()
    }
  }

  return (
    <div className="status-bar">
      {/* Left – service indicators */}
      <div className="status-bar-left">
        <button
          className="status-item status-services"
          title={
            error
              ? `Error: ${error}`
              : `Gateway: ${gateway}  |  UI: ${ui}${pid ? `  |  PID ${pid}` : ''}\nClick to start if stopped`
          }
          onClick={handleServiceClick}
        >
          <span className={`svc-dot ${CLS[gateway] || 'svc-muted'}`} title={`Gateway :8790 — ${gateway}`}>
            {DOT[gateway] || '○'} GW
          </span>
          <span className="svc-sep">·</span>
          <span className={`svc-dot ${CLS[ui] || 'svc-muted'}`} title={`UI :2151 — ${ui}`}>
            {DOT[ui] || '○'} UI
          </span>
        </button>

        <span className="status-item status-branch" title={`Branch: ${state.gitBranch}`}>
          ⎇ {state.gitBranch}
        </span>
      </div>

      {/* Center – streaming indicator */}
      <div className="status-bar-center">
        {activeRunId && (
          <button
            className="status-item status-bg-run"
            title={`Background run active (${activeRunId}). Click to open Studio.`}
            onClick={() => dispatch({ type: 'SET_VIEW', view: 'studio' })}
          >
            <span className="pulse-dot" />
            <span>Background run</span>
            <span className="status-bg-run-id">#{runLabel}</span>
          </button>
        )}
        {state.streaming && (
          <span className="status-item status-streaming">
            <span className="pulse-dot" /> Agent running…
          </span>
        )}
        {(ui === 'starting' || gateway === 'starting') && !state.streaming && (
          <span className="status-item status-starting">
            <span className="pulse-dot" /> Starting services…
          </span>
        )}
      </div>

      {/* Right */}
      <div className="status-bar-right">
        {activeTab && (
          <>
            <span className="status-item">{activeTab.language || 'plain'}</span>
            <span className="status-divider" />
          </>
        )}
        <span className="status-item">
          {time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
        <button
          className="status-item status-btn"
          title="Toggle Terminal (Ctrl+`)"
          onClick={() => dispatch({ type: 'TOGGLE_TERMINAL' })}
        >⌨</button>
        <button
          className="status-item status-btn"
          title="Command Palette (Ctrl+Shift+P)"
          onClick={() => dispatch({ type: 'TOGGLE_COMMAND_PALETTE' })}
        >⌘</button>
      </div>
    </div>
  )
}
