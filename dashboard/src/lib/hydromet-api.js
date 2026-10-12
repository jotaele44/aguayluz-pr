import { API_BASE, getApiKey } from '@/lib/api'

// Client for the NWS hydromet plane (server/backend/hydromet_api.py).
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

async function getJSON(path, fallback) {
  if (OFFLINE) return fallback
  try {
    const response = await fetch(`${API_BASE}${path}`, { signal: AbortSignal.timeout(8000) })
    if (!response.ok) return fallback
    return await response.json()
  } catch {
    return fallback
  }
}

const qs = (params) => {
  const pairs = Object.entries(params).filter(([, value]) => value != null && value !== '' && value !== false)
  return pairs.length ? `?${new URLSearchParams(pairs).toString()}` : ''
}

const EMPTY_FC = { type: 'FeatureCollection', features: [] }

export const getHydrometSummary = () => getJSON('/hydromet/summary', null)

export const getHydrometSources = () => getJSON('/hydromet/sources', null)

export const getRiverGauges = (filters = {}) => getJSON(
  `/hydromet/gauges${qs(filters)}`,
  { total: 0, items: [] },
)

export const getRiverGaugesGeojson = () => getJSON('/hydromet/gauges.geojson', EMPTY_FC)

export const getHydrometRefreshStatus = () => getJSON('/hydromet/refresh/status', null)

// Runs the source's ingest on the backend, then rebuilds alerts. Throws on any
// non-2xx so react-query routes it to onError with an actionable message.
export const postHydrometRefresh = async (sourceId) => {
  if (OFFLINE) throw new Error('Refresh is unavailable in the offline export.')
  const key = getApiKey()
  const res = await fetch(`${API_BASE}/hydromet/refresh/${encodeURIComponent(sourceId)}`, {
    method: 'POST',
    headers: key ? { Authorization: `Bearer ${key}` } : {},
    signal: AbortSignal.timeout(300000),
  })
  if (res.status === 401) {
    throw new Error(key
      ? 'Refresh rejected: the API key set in System & Tools is not accepted by this backend.'
      : 'Refresh refused: API key auth is enabled on the backend. Set the key in System & Tools.')
  }
  if (res.status === 409) throw new Error('A hydromet refresh is already running.')
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const failed = body?.steps?.find((step) => step.return_code !== 0)
    const detail = failed ? `${failed.script}: ${(failed.stderr_tail || failed.stdout_tail || '').slice(-300)}` : ''
    throw new Error(`Refresh failed (HTTP ${res.status}). ${detail}`.trim())
  }
  return body
}
