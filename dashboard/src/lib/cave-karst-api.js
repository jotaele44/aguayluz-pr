import { API_BASE } from '@/lib/api'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

async function getJSON(path, fallback) {
  if (OFFLINE) return fallback
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      signal: AbortSignal.timeout(8000),
    })
    if (!response.ok) return fallback
    return await response.json()
  } catch {
    return fallback
  }
}

const qs = (params) => {
  const pairs = Object.entries(params).filter(([, value]) => value != null && value !== '')
  return pairs.length ? `?${new URLSearchParams(pairs).toString()}` : ''
}

export const getCaveKarstSummary = () => getJSON('/cave-karst/summary', null)

export const getCaveKarstAssets = (filters = {}) => getJSON(
  `/cave-karst/assets${qs(filters)}`,
  { total: 0, items: [] },
)

export const getCaveKarstAsset = (assetId) => getJSON(
  `/cave-karst/assets/${encodeURIComponent(assetId)}`,
  null,
)

export const getCaveKarstStatusHistory = (assetId) => getJSON(
  `/cave-karst/assets/${encodeURIComponent(assetId)}/status-history`,
  { asset_id: assetId, total: 0, items: [] },
)

export const getCaveKarstProvenance = (assetId) => getJSON(
  `/cave-karst/assets/${encodeURIComponent(assetId)}/provenance`,
  { asset_id: assetId, total: 0, items: [] },
)

export const getCaveKarstEdges = (assetId) => getJSON(
  `/cave-karst/assets/${encodeURIComponent(assetId)}/edges`,
  { asset_id: assetId, total: 0, items: [] },
)

export const getCaveKarstAlerts = (filters = {}) => getJSON(
  `/cave-karst/alerts${qs(filters)}`,
  { total: 0, items: [] },
)
