import React from 'react'
import ReactDOM from 'react-dom/client'
import * as Sentry from '@sentry/react'
// Self-hosted fonts (bundled; no external request — keeps the offline single-file export clean).
import '@fontsource-variable/inter'
import '@fontsource/jetbrains-mono'
import App from '@/App.jsx'
import '@/index.css'
import '@pr-federation/react/styles.css'
import '@/styles/federation.css'
import 'maplibre-gl/dist/maplibre-gl.css'

// This app commits to a dark slate/sky design. Stamp the shared federation.css
// signals so its accent + dark tokens apply consistently across the federation.
document.documentElement.dataset.repo = 'aguayluz-pr'
document.documentElement.dataset.theme = 'dark'

const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN

if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    integrations: [Sentry.browserTracingIntegration(), Sentry.replayIntegration({ maskAllText: false, blockAllMedia: false })],
    tracesSampleRate: 0.1,
    replaysSessionSampleRate: 0.05,
    replaysOnErrorSampleRate: 1.0,
    environment: import.meta.env.MODE,
  })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <App />
)
