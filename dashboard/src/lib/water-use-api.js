import { API_BASE } from '@/lib/api'

// Client for the USGS Puerto Rico water-use estimates (server/backend/water_use_api.py).
// Read-only: the sources are static publications re-read on demand, so there is no refresh route.
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

// What the static offline export shows: no estimates, and no claim that any exist.
export const EMPTY_WATER_USE = {
  scope: null,
  generated_at: null,
  source: null,
  categories: [],
  counts: { records: 0, years: 0 },
  years: [],
  municipios: { public_supply: {}, irrigation: {} },
  restatements: [],
  related: null,
}

// A live request failure throws so the query reaches its error state (and the panel offers a
// retry) instead of reading as "no estimates".
export const getWaterUseEstimates = async () => {
  if (OFFLINE) return EMPTY_WATER_USE
  const response = await fetch(`${API_BASE}/water-use/estimates`, { signal: AbortSignal.timeout(8000) })
  if (!response.ok) throw new Error(`HTTP ${response.status} from /water-use/estimates`)
  return response.json()
}
