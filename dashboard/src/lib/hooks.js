import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getHealth, getAssets, getAssetsGeojson, getMunicipiosGeojson,
  getEvents, getEventsPaged, getAssetEvents, getMunicipioSummary,
  getReadings, getReviewQueue, getReviewQueuePaged,
  getSummary, getSummarySectors, postDecision, postRunExport,
} from '@/lib/api'

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 15_000 })
export const useSummary = () => useQuery({ queryKey: ['summary'], queryFn: getSummary })
export const useSummarySectors = () => useQuery({ queryKey: ['summary/sectors'], queryFn: getSummarySectors })
export const useAssets = (f = {}) => useQuery({ queryKey: ['assets', f], queryFn: () => getAssets(f) })
export const useAssetsGeojson = () => useQuery({ queryKey: ['assets.geojson'], queryFn: getAssetsGeojson })
export const useMunicipiosGeojson = () => useQuery({ queryKey: ['municipios.geojson'], queryFn: getMunicipiosGeojson })
// Default page size so a normal load doesn't pull the entire service-events
// corpus (the full SDWIS violation history is ~25k rows / ~13 MB). The backend
// returns the most-recent events first; callers can override `limit` (or pass a
// negative limit) to fetch more.
export const DEFAULT_EVENT_LIMIT = 500
export const useEvents = (f = {}) => {
  const params = { limit: DEFAULT_EVENT_LIMIT, ...f }
  return useQuery({ queryKey: ['events', params], queryFn: () => getEvents(params) })
}
export const useEventsPaged = (f = {}) => {
  const params = { limit: DEFAULT_EVENT_LIMIT, ...f }
  return useQuery({ queryKey: ['events/paged', params], queryFn: () => getEventsPaged(params) })
}
export const useAssetEvents = (id) => useQuery({ queryKey: ['asset-events', id], queryFn: () => getAssetEvents(id), enabled: !!id })
export const useMunicipioSummary = (name) => useQuery({ queryKey: ['municipio', name], queryFn: () => getMunicipioSummary(name), enabled: !!name })
export const useReadings = (f = {}) => useQuery({ queryKey: ['readings', f], queryFn: () => getReadings(f) })
export const useReviewQueue = (f = {}) => useQuery({ queryKey: ['review', f], queryFn: () => getReviewQueue(f) })
export const useReviewQueuePaged = (f = {}) => useQuery({ queryKey: ['review/paged', f], queryFn: () => getReviewQueuePaged(f) })

export const useDecision = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ ref, decision }) => postDecision(ref, decision),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review'] })
      qc.invalidateQueries({ queryKey: ['review/paged'] })
    },
  })
}

export const useRunExport = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: postRunExport,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['health'] })
      qc.invalidateQueries({ queryKey: ['review'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
    },
  })
}
