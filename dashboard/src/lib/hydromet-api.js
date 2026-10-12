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

// Like getJSON, but a live request failure throws so the query reaches its error state
// (and the panel shows it with a retry) instead of reading as "no data".
async function getJSONOrThrow(path, offlineFallback) {
  if (OFFLINE) return offlineFallback
  const response = await fetch(`${API_BASE}${path}`, { signal: AbortSignal.timeout(8000) })
  if (!response.ok) throw new Error(`HTTP ${response.status} from ${path}`)
  return response.json()
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

// Stage IV rainfall per municipio for one window ('1day' | 'last7days' | 'last30days')
// and data day (YYYY-MM-DD; omitted = latest).
export const getRainfall = ({ window = '1day', date } = {}) => getJSONOrThrow(
  `/hydromet/rainfall${qs({ window, date })}`,
  { window, data_date: null, available_dates: [], windows: [], thresholds: null, files: [], total: 0, items: [] },
)

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
