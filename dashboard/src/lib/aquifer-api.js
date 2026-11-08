import { API_BASE } from '@/lib/api'

// Client for the PRDNER aquifer condition bands (server/backend/aquifer_api.py). Read-only:
// the producer is scheduled and there is deliberately no refresh route to call.
const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

// What the static offline export shows: no bands, and no claim that any exist.
export const EMPTY_AQUIFER_BANDS = {
  scope: null,
  generated_at: null,
  source: null,
  classes: [],
  counts: { wells: 0, with_reading: 0, provisional_readings: 0, stale_readings: 0, critical: 0 },
  items: [],
}

// A live request failure throws so the query reaches its error state (and the panel offers a
// retry) instead of reading as "no wells".
export const getAquiferBands = async () => {
  if (OFFLINE) return EMPTY_AQUIFER_BANDS
  const response = await fetch(`${API_BASE}/aquifer/bands`, { signal: AbortSignal.timeout(8000) })
  if (!response.ok) throw new Error(`HTTP ${response.status} from /aquifer/bands`)
  return response.json()
}
