import React from 'react'

function formatErrorMessage(error) {
  if (!error) return 'Unknown renderer failure.'
  const message = String(error?.message || error || '').trim()
  return message || 'Unknown renderer failure.'
}

export default class RendererErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    this.setState({ error, info })
    try {
      console.error('RendererErrorBoundary caught an error', error, info)
    } catch (_) {}
  }

  handleReload = () => {
    try {
      window.location.reload()
    } catch (_) {}
  }

  render() {
    const { error, info } = this.state
    if (!error) return this.props.children

    const detail = String(info?.componentStack || '').trim()
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          padding: 24,
          background: 'radial-gradient(circle at top, rgba(232, 117, 88, 0.14), transparent 42%), #0d0f14',
          color: '#f3f4f6',
        }}
      >
        <div
          style={{
            width: 'min(760px, 100%)',
            borderRadius: 20,
            border: '1px solid rgba(255,255,255,0.12)',
            background: 'rgba(15, 23, 42, 0.88)',
            boxShadow: '0 18px 48px rgba(0,0,0,0.32)',
            padding: 24,
          }}
        >
          <div style={{ fontSize: 12, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#fca5a5', marginBottom: 10 }}>
            Renderer Recovery
          </div>
          <div style={{ fontSize: 28, fontWeight: 700, marginBottom: 12 }}>
            Kendr hit a renderer error.
          </div>
          <div style={{ fontSize: 15, lineHeight: 1.6, color: '#cbd5e1', marginBottom: 18 }}>
            The app stayed open instead of falling through to a blank screen. Reload the window and try the same action again.
          </div>
          <div
            style={{
              borderRadius: 14,
              border: '1px solid rgba(252, 165, 165, 0.26)',
              background: 'rgba(127, 29, 29, 0.22)',
              padding: 14,
              marginBottom: 18,
              fontFamily: "'Cascadia Code', 'Fira Code', monospace",
              fontSize: 13,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {formatErrorMessage(error)}
            {detail ? `\n\n${detail}` : ''}
          </div>
          <button
            type="button"
            onClick={this.handleReload}
            style={{
              border: 'none',
              borderRadius: 10,
              background: '#f97316',
              color: '#111827',
              fontWeight: 700,
              padding: '11px 16px',
              cursor: 'pointer',
            }}
          >
            Reload Kendr
          </button>
        </div>
      </div>
    )
  }
}
