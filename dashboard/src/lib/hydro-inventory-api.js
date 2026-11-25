import { API_BASE } from '@/lib/api'

// Client for the Puerto Rico hydrologic feature inventory (server/backend/hydro_inventory_api.py).
// Read-only: the ingests are run by a maintainer, so there is no refresh route to call.
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

// What the static offline export shows: no inventory, and no claim that one exists.
export const EMPTY_HYDRO_SUMMARY = {
  scope: null,
  generated_at: null,
  phase_scope: null,
  coverage: null,
  source_ledgers: {},
  spatial: null,
  open_residue: [],
  datum: null,
  monitoring: { readings_present: false, wells_by_state: {} },
  conflicts: 0,
  sources: [],
  related: null,
}
export const EMPTY_LIST = { total: 0, offset: 0, limit: 0, items: [] }

const get = async (path, params = {}) => {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString()
  const url = `${API_BASE}${path}${query ? `?${query}` : ''}`
  const response = await fetch(url, { signal: AbortSignal.timeout(15000) })
  if (!response.ok) throw new Error(`HTTP ${response.status} from ${path}`)
  return response.json()
}

// A live request failure throws so the query reaches its error state (and the panel offers a
// retry) instead of reading as "no features".
export const getHydroSummary = async () => (OFFLINE ? EMPTY_HYDRO_SUMMARY : get('/hydro/inventory/summary'))
export const getHydroFeatures = async (params) => (OFFLINE ? EMPTY_LIST : get('/hydro/features', params))
export const getHydroFeature = async (id) => (OFFLINE ? null : get(`/hydro/features/${encodeURIComponent(id).replaceAll('%3A', ':')}`))
export const getHydroConflicts = async () => (OFFLINE ? EMPTY_LIST : get('/hydro/conflicts'))
export const getHydroCandidates = async (params) => (OFFLINE ? EMPTY_LIST : get('/hydro/candidates', params))
export const getAquiferWells = async (aquifer, includePolygon) => (OFFLINE
  ? { aquifer, include_polygon: includePolygon, site_nos: [], wells: 0, authoritative: 0, polygon_only: 0 }
  : get('/hydro/aquifer-wells', { aquifer, include_polygon: includePolygon ? 'true' : undefined }))
export const getAquiferSeries = async (aquifer, includePolygon) => (OFFLINE
  ? { aquifer, readings_present: false, points: [], provisional_points: [], members: [], contributing_wells: [] }
  : get('/hydro/aquifer-series', { aquifer, include_polygon: includePolygon ? 'true' : undefined }))
export const getStreamTiles = async () => (OFFLINE ? { tiles: [] } : get('/hydro/stream-tiles'))
// Map geometry URLs, handed straight to MapLibre as GeoJSON sources.
export const hydroGeoUrl = (name) => `${API_BASE}/hydro/geo/${name}.geojson`
export const hydroPointsUrl = (type) => `${API_BASE}/hydro/points.geojson?type=${type}`
export const hydroAquifersUrl = () => `${API_BASE}/hydro/aquifers.geojson`
