// REST client for the AguaYLuz-PR FastAPI backend.
// Backend: server/backend/main.py  (uvicorn server.backend.main:app --port 8000)
// Reads the module's REAL canonical JSONL + GeoJSON + outputs.
import snapshot from './snapshot.json' // {} in normal builds; populated for VITE_OFFLINE exports
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// Offline export build: resolve from an embedded data snapshot instead of fetching.
// (A file:// page cannot fetch at all, so standalone exports bake the data in.)
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

// ── Write credential ────────────────────────────────────────────────────────
// The backend's mutating routes are guarded by `_require_key` when API_SECRET_KEY
// is set (server/backend/main.py). The operator supplies that key here.
//
// sessionStorage, deliberately, and not a VITE_ build variable: `npm run
// build:export` inlines the whole app into one distributable HTML file, so a
// build-time secret would travel with every exported report. sessionStorage also
// clears when the tab closes, which is the right lifetime for a shared key typed
// into a diagnostic tool.
const API_KEY_STORAGE_KEY = 'aguayluz_api_key'

export const getApiKey = () => {
  if (typeof window === 'undefined') return ''
  try {
    return window.sessionStorage.getItem(API_KEY_STORAGE_KEY) || ''
  } catch {
    return '' // private-mode / storage disabled
  }
}

export const setApiKey = (key) => {
  if (typeof window === 'undefined') return
  try {
    if (key) window.sessionStorage.setItem(API_KEY_STORAGE_KEY, key)
    else window.sessionStorage.removeItem(API_KEY_STORAGE_KEY)
  } catch {
    // storage disabled — the key simply will not persist
  }
}

// Merged into every mutating request. Absent when no key is set, so a backend
// with auth disabled sees exactly the requests it saw before.
const authHeaders = () => {
  const key = getApiKey()
  return key ? { Authorization: `Bearer ${key}` } : {}
}

const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...authHeaders() })

// A 401 means the backend has auth on and we either sent nothing or sent the
// wrong key. Say which, rather than surfacing a bare status code — the operator
// can act on the first and not the second.
const authFailureMessage = () =>
  getApiKey()
    ? 'Rejected: the API key set in System & Tools is not accepted by this backend.'
    : 'Refused: API key auth is enabled on the backend. Set the key in System & Tools.'

async function getJSON(path, fallback = null) {
  if (OFFLINE) {
    const key = path.split('?')[0] // server-side filters degrade to the unfiltered snapshot
    return key in snapshot ? snapshot[key] : fallback
  }
  try {
    const res = await fetch(`${API_BASE}${path}`, { signal: AbortSignal.timeout(8000) })
    if (!res.ok) return fallback
    return await res.json()
  } catch {
    return fallback
  }
}

const qs = (params) => {
  const p = Object.entries(params).filter(([, v]) => v != null && v !== '')
  return p.length ? '?' + new URLSearchParams(p).toString() : ''
}

export const getHealth = () => getJSON('/health', { status: 'down', counts: {}, readiness: {} })
export const getAssets = (f = {}) => getJSON(`/assets${qs(f)}`, [])
export const getAssetsGeojson = () => getJSON('/assets.geojson', { type: 'FeatureCollection', features: [] })
export const getMunicipiosGeojson = () => getJSON('/municipios.geojson', { type: 'FeatureCollection', features: [] })
// /events returns {total, offset, items}; getEvents unwraps to the array for backward compat.
export const getEvents = async (f = {}) => {
  const r = await getJSON(`/events${qs(f)}`, { items: [] })
  return r?.items ?? r ?? []
}
export const getEventsPaged = (f = {}) => getJSON(`/events${qs(f)}`, { total: 0, offset: 0, items: [] })
export const getAssetEvents = (id) => getJSON(`/assets/${id}/events`, [])
export const getMunicipioSummary = (name) => getJSON(`/municipios/${encodeURIComponent(name)}/summary`, null)
export const getReadings = (f = {}) => getJSON(`/readings${qs(typeof f === 'string' ? { kind: f } : f)}`, [])
// /review-queue returns {total, offset, items}
export const getReviewQueue = async (f = {}) => {
  const r = await getJSON(`/review-queue${qs(f)}`, { items: [] })
  return r?.items ?? r ?? []
}
export const getReviewQueuePaged = (f = {}) => getJSON(`/review-queue${qs(f)}`, { total: 0, offset: 0, items: [] })
export const getSummary = () => getJSON('/summary', {})
export const getSummarySectors = () => getJSON('/summary/sectors', {})
export const getCoverage = () => getJSON('/summary/coverage', null)
export const getSystemStatus = () => getJSON('/system/status', null)

// Operational alert layer (docs/ALERT_SYSTEM.md). /alerts returns {total, offset, items}
// like /events; getAlerts unwraps to the array for panel-style consumers.
export const getAlertsPaged = (f = {}) => getJSON(`/alerts${qs(f)}`, { total: 0, offset: 0, items: [] })
export const getAlerts = async (f = {}) => {
  const r = await getAlertsPaged(f)
  return r?.items ?? []
}
export const getAlert = (id) => getJSON(`/alerts/${encodeURIComponent(id)}`, null)
export const getAlertFacets = () => getJSON('/alerts/facets', null)
export const getAlertsGeojson = (f = {}) => getJSON(`/alerts.geojson${qs(f)}`, { type: 'FeatureCollection', features: [] })
export const getAlertDependencies = (f = {}) => getJSON(`/alerts/dependencies${qs(f)}`, [])
export const getAlertGaps = () => getJSON('/alerts/gaps', [])
export const postDecision = async (ref, decision) => {
  if (OFFLINE) return { ok: true }
  const res = await fetch(`${API_BASE}/review-queue/${encodeURIComponent(ref)}/decision`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ decision }),
    signal: AbortSignal.timeout(8000),
  })
  if (res.status === 401) throw new Error(`Decision ${authFailureMessage()}`)
  return res.json()
}
export const postRunExport = async () => {
  if (OFFLINE) return { ok: true }
  const res = await fetch(`${API_BASE}/admin/run-export`, {
    method: 'POST',
    headers: authHeaders(),
    signal: AbortSignal.timeout(120000),
  })
  // Throw on non-2xx so react-query routes it to onError. Returning res.json()
  // unconditionally reported "export complete" for a 401 (auth enabled, no bearer
  // token) or a 500 (the exporter itself failed) — the operator was told outputs
  // were regenerated when nothing ran.
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(
      res.status === 401
        ? `Export ${authFailureMessage()}`
        : `Export failed (HTTP ${res.status}). ${detail.slice(0, 300)}`,
    )
  }
  return res.json()
}

export const postAiQuery = async (query) => {
  if (OFFLINE) return { answer: 'AI query not available in offline mode.' }
  try {
    const res = await fetch(`${API_BASE}/ai/query`, {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ query }),
      signal: AbortSignal.timeout(30000),
    })
    // This route is key-guarded because it spends the operator's ANTHROPIC_API_KEY.
    if (res.status === 401) return { answer: null, error: `AI query ${authFailureMessage()}` }
    if (!res.ok) return { answer: null, error: `Backend error ${res.status}` }
    return res.json()
  } catch (e) {
    return { answer: null, error: String(e) }
  }
}

export const getEvent = (id) => getJSON(`/events/${encodeURIComponent(id)}`, null)

export const patchEvent = async (id, data) => {
  if (OFFLINE) return null
  const res = await fetch(`${API_BASE}/events/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: jsonHeaders(),
    body: JSON.stringify(data),
    signal: AbortSignal.timeout(8000),
  })
  if (res.status === 401) throw new Error(`Event edit ${authFailureMessage()}`)
  if (!res.ok) throw new Error(`PATCH event failed: ${res.status}`)
  return res.json()
}

export const patchAsset = async (id, data) => {
  if (OFFLINE) return null
  const res = await fetch(`${API_BASE}/assets/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: jsonHeaders(),
    body: JSON.stringify(data),
    signal: AbortSignal.timeout(8000),
  })
  if (res.status === 401) throw new Error(`Asset edit ${authFailureMessage()}`)
  if (!res.ok) throw new Error(`PATCH asset failed: ${res.status}`)
  return res.json()
}

export const getReportUrl = () => `${API_BASE}/export/report.html`

export const postNotify = async ({ message, title }) => {
  if (OFFLINE) return { ok: false, error: 'Notifications not available in offline mode.' }
  try {
    const res = await fetch(`${API_BASE}/notify`, {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({ message, title }),
      signal: AbortSignal.timeout(15000),
    })
    if (res.status === 401) return { ok: false, error: `Notify ${authFailureMessage()}` }
    if (!res.ok) return { ok: false, error: `Backend error ${res.status}` }
    return res.json()
  } catch (e) {
    return { ok: false, error: String(e) }
  }
}
