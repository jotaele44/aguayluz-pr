import { getJSON } from '@/lib/api'

const qs = (filters = {}) => {
  const pairs = Object.entries(filters)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => [key, String(value)])
  return pairs.length ? `?${new URLSearchParams(pairs).toString()}` : ''
}

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
