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
export const getEvents = (f = {}) => getJSON(`/events${qs(f)}`, [])
export const getReadings = (kind = 'reservoir') => getJSON(`/readings${qs({ kind })}`, [])
export const getReviewQueue = () => getJSON('/review-queue', [])
export const getSummary = () => getJSON('/summary', {})
