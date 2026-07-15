import { Component } from 'react'
import { AlertTriangle } from 'lucide-react'
import * as Sentry from '@sentry/react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    if (import.meta.env.VITE_SENTRY_DSN) {
      Sentry.captureException(error, { extra: { componentStack: info.componentStack, label: this.props.label } })
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center h-full min-h-[120px] gap-2 text-slate-400 p-4">
          <AlertTriangle className="h-5 w-5 text-amber-400" />
          <p className="text-xs text-center">
            {this.props.label ?? 'Panel'} failed to render.
          </p>
          <button
            className="text-[11px] underline text-slate-500 hover:text-slate-300"
            onClick={() => this.setState({ error: null })}
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
