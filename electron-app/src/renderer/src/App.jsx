import React from 'react'
import { useApp } from './contexts/AppContext'
import StatusBar from './components/StatusBar'
import CommandPalette from './components/CommandPalette'
import MenuBar from './components/MenuBar'
import StudioLayout from './panels/StudioLayout'
import AgentOrchestration from './panels/AgentOrchestration'
import SkillsPanel from './panels/SkillsPanel'
import ProjectWorkspace from './panels/ProjectWorkspace'
import HomePanel from './panels/HomePanel'
import BuildHub from './panels/BuildHub'
import IntegrationsHub from './panels/IntegrationsHub'
import MachineHub from './panels/MachineHub'
import MemoryHub from './panels/MemoryHub'
import SettingsHub from './panels/SettingsHub'

const PRIMARY_NAV = [
  { id: 'home', label: 'Home' },
  { id: 'studio', label: 'Studio' },
  { id: 'build', label: 'Build' },
  { id: 'machine', label: 'Machine' },
  { id: 'memory', label: 'Memory' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'runs', label: 'Runs' },
  { id: 'marketplace', label: 'Marketplace' },
  { id: 'settings', label: 'Settings' },
]

export default function App() {
  const { state, dispatch } = useApp()

  return (
    <div className="app-root">
      <div className="titlebar" style={{ WebkitAppRegion: 'drag' }}>
        <div className="titlebar-icon titlebar-icon--brand" style={{ WebkitAppRegion: 'no-drag' }}>
          K
        </div>
        <div className="titlebar-brand" style={{ WebkitAppRegion: 'no-drag' }}>
          <span className="titlebar-brand__name">Kendr</span>
          <span className="titlebar-brand__tag">AI Operating System</span>
        </div>
        <MenuBar />
        <div className="titlebar-center" style={{ WebkitAppRegion: 'drag' }}>
          {!['home', 'studio'].includes(state.activeView) && (
            <span className="titlebar-project">{state.projectRoot ? state.projectRoot.split(/[\\/]/).pop() : 'Workspace'}</span>
          )}
        </div>
        <ModeSwitch />
      </div>

      <div className="shell-nav">
        <div className="shell-nav__items">
          {PRIMARY_NAV.map((item) => (
            <button
              key={item.id}
              className={`shell-nav__item ${state.activeView === item.id ? 'active' : ''}`}
              onClick={() => dispatch({ type: 'SET_VIEW', view: item.id })}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="shell-nav__status">
          <span className={`status-chip ${state.backendStatus === 'running' ? 'ok' : 'warn'}`}>
            {state.backendStatus === 'running' ? 'Connected' : state.backendStatus}
          </span>
          <span className="status-chip neutral">{state.selectedModel || 'Auto routing'}</span>
        </div>
      </div>

      <div className="app-body app-body--shell">
        <RenderActiveView />
      </div>

      <StatusBar />
      {state.commandPaletteOpen && <CommandPalette />}
    </div>
  )
}

function RenderActiveView() {
  const { state } = useApp()

  switch (state.activeView) {
    case 'home':
      return <HomePanel />
    case 'studio':
      return <StudioLayout />
    case 'build':
      return <BuildHub />
    case 'machine':
      return <MachineHub />
    case 'memory':
      return <MemoryHub />
    case 'integrations':
      return <IntegrationsHub />
    case 'runs':
      return <AgentOrchestration />
    case 'marketplace':
      return <SkillsPanel />
    case 'settings':
      return <SettingsHub />
    case 'developer':
      return <ProjectWorkspace />
    default:
      return <HomePanel />
  }
}

function ModeSwitch() {
  const { state, dispatch } = useApp()

  return (
    <div className="ms-switch" style={{ WebkitAppRegion: 'no-drag' }}>
      <button
        className={`ms-btn ${state.appMode === 'developer' ? 'active' : ''}`}
        onClick={() => {
          dispatch({ type: 'SET_APP_MODE', mode: 'developer' })
          dispatch({ type: 'SET_VIEW', view: 'developer' })
        }}
        title="Developer workspace"
      >
        <DevIcon /> Developer
      </button>
      <button
        className={`ms-btn ${state.appMode === 'studio' ? 'active' : ''}`}
        onClick={() => {
          dispatch({ type: 'SET_APP_MODE', mode: 'studio' })
          dispatch({ type: 'SET_VIEW', view: 'studio' })
        }}
        title="Studio workspace"
      >
        <StudioIcon /> Studio
      </button>
    </div>
  )
}

function DevIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  )
}

function StudioIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5" />
      <path d="M2 12l10 5 10-5" />
    </svg>
  )
}
