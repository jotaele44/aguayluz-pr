// REST client for the AguaYLuz-PR FastAPI backend.
// Backend: server/backend/main.py  (uvicorn server.backend.main:app --port 8000)
// Reads the module's REAL canonical JSONL + GeoJSON + outputs.
import snapshot from './snapshot.json' // {} in normal builds; populated for VITE_OFFLINE exports
export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// Offline export build: resolve from an embedded data snapshot instead of fetching.
// (A file:// page cannot fetch at all, so standalone exports bake the data in.)
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

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
export const postDecision = async (ref, decision) => {
  if (OFFLINE) return { ok: true }
  const res = await fetch(`${API_BASE}/review-queue/${encodeURIComponent(ref)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision }),
    signal: AbortSignal.timeout(8000),
  })
  return res.json()
}
export const postRunExport = async () => {
  if (OFFLINE) return { ok: true }
  const res = await fetch(`${API_BASE}/admin/run-export`, {
    method: 'POST',
    signal: AbortSignal.timeout(120000),
  })
  return res.json()
}

export const postMycelialQuery = async (query, conditions) => {
  if (OFFLINE) return { status: 'offline', answer: 'Mycelial assistant requires the local backend.' }
  const res = await fetch(`${API_BASE}/mycelial/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, conditions }),
    signal: AbortSignal.timeout(8000),
  })
  const payload = await res.json()
  if (!res.ok) throw new Error(payload?.detail ?? 'Mycelial query failed')
  return payload
}
