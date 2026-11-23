import { API_BASE } from '@/lib/api'

export async function getHydroSourceReadiness() {
  if (import.meta.env.VITE_OFFLINE === '1') {
    return { sources: [], source_registry_state: 'OFFLINE_UNVERIFIED',
      certification: 'WITHHELD', operational_ingestion: false }
  }
  const response = await fetch(`${API_BASE}/hydro-intelligence/sources`, {
    signal: AbortSignal.timeout(8000),
  })
  if (!response.ok) throw new Error(`Hydro readiness request failed (HTTP ${response.status})`)
  return response.json()
}
