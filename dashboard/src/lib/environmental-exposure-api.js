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

// Entity kinds that make up the solid-waste site registry (ADR-0004).
export const SOLID_WASTE_KINDS = ['LANDFILL', 'SOLID_WASTE_FACILITY', 'DISPOSAL_SITE']

// One request per kind because the endpoint filters on a single entity_kind.
// `total` is the sum of the server-reported totals, not items.length, so the
// caller can tell a truncated or failed list from a complete one.
export async function getSolidWasteSites() {
  const pages = await Promise.all(
    SOLID_WASTE_KINDS.map((kind) => getEnvironmentalExposureEntities({ entity_kind: kind, limit: 500 })),
  )
  return {
    total: pages.reduce((sum, page) => sum + (page?.total ?? 0), 0),
    items: pages.flatMap((page) => page?.items ?? []),
  }
}

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
