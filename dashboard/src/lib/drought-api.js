import { API_BASE, getAlertsGeojson, getEvents, getLumaOutageStatus, getReadings } from '@/lib/api'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'
const EMPTY_FC = { type: 'FeatureCollection', features: [] }
const EMPTY_SUMMARY = {
  schema_version: 'aguayluz.drought-operations-api/v0.1',
  status: 'unavailable',
  map_date: null,
  freshness: { state: 'UNKNOWN', age_days: null, max_age_days: 10 },
  statistics: null,
  history: [],
  change: null,
  municipio_date: null,
  municipios: [],
  source_manifestations: {},
  limitations: ['No committed USDM footprint artifact is available yet.'],
}

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

export const getDroughtSummary = () => getJSON('/drought/summary', EMPTY_SUMMARY)
export const getDroughtFootprint = () => getJSON('/drought/footprint.geojson', EMPTY_FC)

export const getDroughtReservoirReadings = async () => {
  const result = await getReadings({ kind: 'reservoir' })
  return Array.isArray(result) ? result : (result?.items ?? [])
}

export const getDroughtAlertsGeojson = () => getAlertsGeojson({ status: 'active' })
export const getDroughtOutageEvents = () => getEvents({ type: 'outage', limit: 500 })
export const getDroughtOutageStatus = () => getLumaOutageStatus({ limit: 4 })
