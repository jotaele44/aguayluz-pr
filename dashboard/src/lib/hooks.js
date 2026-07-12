import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getHealth, getAssets, getAssetsGeojson, getMunicipiosGeojson,
  getMycelialObservations, getMycelialObservationsGeojson, getMycelialGridGeojson, getMycelialSummary,
  getEvents, getEventsPaged, getAssetEvents, getMunicipioSummary,
  getReadings, getReviewQueue, getReviewQueuePaged,
  getSummary, getSummarySectors, postDecision, postRunExport,
} from '@/lib/api'

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 15_000 })
export const useSummary = () => useQuery({ queryKey: ['summary'], queryFn: getSummary })
export const useSummarySectors = () => useQuery({ queryKey: ['summary/sectors'], queryFn: getSummarySectors })
export const useMycelialSummary = () => useQuery({ queryKey: ['mycelial-summary'], queryFn: getMycelialSummary })
export const useAssets = (f = {}) => useQuery({ queryKey: ['assets', f], queryFn: () => getAssets(f) })
export const useAssetsGeojson = () => useQuery({ queryKey: ['assets.geojson'], queryFn: getAssetsGeojson })
export const useMunicipiosGeojson = () => useQuery({ queryKey: ['municipios.geojson'], queryFn: getMunicipiosGeojson })
export const useMycelialObservations = (f = {}) => useQuery({ queryKey: ['mycelial-observations', f], queryFn: () => getMycelialObservations(f) })
export const useMycelialObservationsGeojson = () => useQuery({ queryKey: ['mycelial-observations.geojson'], queryFn: getMycelialObservationsGeojson })
export const useMycelialGridGeojson = () => useQuery({ queryKey: ['mycelial-grid.geojson'], queryFn: getMycelialGridGeojson })
export const useEvents = (f = {}) => useQuery({ queryKey: ['events', f], queryFn: () => getEvents(f) })
export const useEventsPaged = (f = {}) => useQuery({ queryKey: ['events/paged', f], queryFn: () => getEventsPaged(f) })
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
      qc.invalidateQueries({ queryKey: ['mycelial-summary'] })
    },
  })
}
