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

export const getEnvironmentalExposureSummary = () => getJSON(
  '/environmental-exposure/summary',
  null,
)

export const getEnvironmentalExposureEntities = (filters = {}) => getJSON(
  `/environmental-exposure/entities${qs(filters)}`,
  { total: 0, items: [] },
)

export const getEnvironmentalExposureRelationships = (filters = {}) => getJSON(
  `/environmental-exposure/relationships${qs(filters)}`,
  { total: 0, items: [] },
)

export const getEnvironmentalExposureIntegrity = () => getJSON(
  '/environmental-exposure/integrity',
  null,
)

export const getHazardSummary = () => getJSON('/hazards/summary', null)

export const getHazardEvents = (filters = {}) => getJSON(
  `/hazards/events${qs(filters)}`,
  { total: 0, items: [] },
)

export const getHazardRelationships = (filters = {}) => getJSON(
  `/hazards/relationships${qs(filters)}`,
  { total: 0, items: [] },
)

export const getHazardSources = () => getJSON('/hazards/sources', null)

export const getHazardIntegrity = () => getJSON('/hazards/integrity', null)
