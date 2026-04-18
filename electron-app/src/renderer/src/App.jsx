import React from 'react'
import { useApp } from './contexts/AppContext'
import StatusBar from './components/StatusBar'
import CommandPalette from './components/CommandPalette'
import MenuBar from './components/MenuBar'
import RendererErrorBoundary from './components/RendererErrorBoundary'
import StudioLayout from './panels/StudioLayout'
import AgentOrchestration from './panels/AgentOrchestration'
import SkillsPanel from './panels/SkillsPanel'
import ProjectWorkspace from './panels/ProjectWorkspace'
import BuildHub from './panels/BuildHub'
import IntegrationsHub from './panels/IntegrationsHub'
import MachineHub from './panels/MachineHub'
import MemoryHub from './panels/MemoryHub'
import SettingsHub from './panels/SettingsHub'
import AboutPanel from './panels/AboutPanel'

export default function App() {
  const { state } = useApp()

  return (
    <RendererErrorBoundary>
      <div className="app-root">
        <div className="titlebar" style={{ WebkitAppRegion: 'drag' }}>
          <div className="titlebar-icon titlebar-icon--brand" style={{ WebkitAppRegion: 'no-drag' }}>
            K
          </div>
          <div className="titlebar-brand" style={{ WebkitAppRegion: 'no-drag' }}>
            <span className="titlebar-brand__name">Kendr</span>
            <span className="titlebar-brand__tag">From research to execution</span>
          </div>
          <MenuBar />
          <div className="titlebar-center" style={{ WebkitAppRegion: 'drag' }}>
            {state.activeView !== 'studio' && (
              <span className="titlebar-project">{state.projectRoot ? state.projectRoot.split(/[\\/]/).pop() : 'Workspace'}</span>
            )}
          </div>
          <ModeSwitch />
          <div className="shell-nav__status">
            <span className={`status-chip ${state.backendStatus === 'running' ? 'ok' : 'warn'}`}>
              {state.backendStatus === 'running' ? 'Connected' : state.backendStatus}
            </span>
            {state.activeView !== 'studio' && (
              <span className="status-chip neutral">{state.selectedModel || 'No model selected'}</span>
            )}
          </div>
        </div>

        <div className="app-body app-body--shell">
          <RenderActiveView />
        </div>

        <StatusBar />
        {state.commandPaletteOpen && <CommandPalette />}
      </div>
    </RendererErrorBoundary>
  )
}

function RenderActiveView() {
  const { state, dispatch } = useApp()

  if (state.activeView === 'studio') return <StudioLayout />

  const titles = {
    build: 'Build',
    machine: 'Machine',
    memory: 'Memory',
    integrations: 'Integrations',
    runs: 'Runs',
    marketplace: 'Marketplace',
    settings: 'Settings',
    developer: 'Developer',
    about: 'About Kendr',
  }

  const content = (() => {
    switch (state.activeView) {
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
      case 'about':
        return <AboutPanel />
      default:
        return <StudioLayout />
    }
  })()

  return (
    <div className="sl-shell-view">
      <div className="sl-back-bar">
        <button className="sl-back-btn" onClick={() => dispatch({ type: 'SET_VIEW', view: 'studio' })}>
          ← Back to search
        </button>
        <div className="sl-back-title">{titles[state.activeView] || 'Workspace'}</div>
      </div>
      <div className="sl-shell-view-body">
        {content}
      </div>
    </div>
  )
}

function ModeSwitch() {
  const { state, dispatch } = useApp()

  return (
    <div className="ms-switch" style={{ WebkitAppRegion: 'no-drag' }}>
      <button
        className={`ms-btn ${state.appMode === 'studio' ? 'active' : ''}`}
        onClick={() => {
          dispatch({ type: 'SET_APP_MODE', mode: 'studio' })
          dispatch({ type: 'SET_VIEW', view: 'studio' })
        }}
      >
        Studio
      </button>
      <button
        className={`ms-btn ${state.appMode === 'developer' ? 'active' : ''}`}
        onClick={() => {
          dispatch({ type: 'SET_APP_MODE', mode: 'developer' })
          dispatch({ type: 'SET_VIEW', view: 'developer' })
        }}
      >
        Developer
      </button>
    </div>
  )
}
