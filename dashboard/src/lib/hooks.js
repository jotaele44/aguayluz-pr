import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getHealth, getAssets, getAssetsGeojson, getMunicipiosGeojson,
  getEvents, getEventsPaged, getAssetEvents, getEvent, getMunicipioSummary,
  getReadings, getReviewQueue, getReviewQueuePaged,
  getSummary, getSummarySectors, getCoverage, getSystemStatus,
  getAlerts, getAlertsPaged, getAlert, getAlertFacets, getAlertsGeojson,
  getAlertDependencies, getAlertGaps,
  postDecision, postRunExport,
  patchEvent, patchAsset,
} from '@/lib/api'

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 15_000 })
export const useSummary = () => useQuery({ queryKey: ['summary'], queryFn: getSummary })
export const useSummarySectors = () => useQuery({ queryKey: ['summary/sectors'], queryFn: getSummarySectors })
export const useAssets = (f = {}) => useQuery({ queryKey: ['assets', f], queryFn: () => getAssets(f) })
export const useAssetsGeojson = () => useQuery({ queryKey: ['assets.geojson'], queryFn: getAssetsGeojson })
export const useMunicipiosGeojson = () => useQuery({ queryKey: ['municipios.geojson'], queryFn: getMunicipiosGeojson })
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
export const useEvent = (id) => useQuery({ queryKey: ['event', id], queryFn: () => getEvent(id), enabled: !!id })
export const useMunicipioSummary = (name) => useQuery({ queryKey: ['municipio', name], queryFn: () => getMunicipioSummary(name), enabled: !!name })
export const useReadingsEnvelope = (f = {}) => useQuery({
  queryKey: ['readings-envelope', f],
  queryFn: async () => {
    const result = await getReadings(f)
    return Array.isArray(result) ? { items: result, quality: null, provenance: null } : result
  },
})
export const useReadings = (f = {}) => useQuery({
  queryKey: ['readings', f],
  queryFn: async () => {
    const result = await getReadings(f)
    return Array.isArray(result) ? result : (result?.items ?? [])
  },
})
export const useReviewQueue = (f = {}) => useQuery({ queryKey: ['review', f], queryFn: () => getReviewQueue(f) })
export const useReviewQueuePaged = (f = {}) => useQuery({ queryKey: ['review/paged', f], queryFn: () => getReviewQueuePaged(f) })
export const useCoverage = () => useQuery({ queryKey: ['summary/coverage'], queryFn: getCoverage })
export const useSystemStatus = () => useQuery({ queryKey: ['system/status'], queryFn: getSystemStatus, refetchInterval: 30_000 })

export const DEFAULT_ALERT_LIMIT = 500
export const useAlerts = (f = {}) => {
  const params = { limit: DEFAULT_ALERT_LIMIT, ...f }
  return useQuery({ queryKey: ['alerts', params], queryFn: () => getAlerts(params) })
}
export const useAlertsPaged = (f = {}) => {
  const params = { limit: DEFAULT_ALERT_LIMIT, ...f }
  return useQuery({ queryKey: ['alerts/paged', params], queryFn: () => getAlertsPaged(params) })
}
export const useAlert = (id) => useQuery({ queryKey: ['alert', id], queryFn: () => getAlert(id), enabled: !!id })
export const useAlertFacets = () => useQuery({ queryKey: ['alerts/facets'], queryFn: getAlertFacets })
export const useAlertsGeojson = (f = {}) => useQuery({ queryKey: ['alerts.geojson', f], queryFn: () => getAlertsGeojson(f) })
export const useAlertDependencies = (f = {}) => useQuery({ queryKey: ['alerts/dependencies', f], queryFn: () => getAlertDependencies(f) })
export const useAlertGaps = () => useQuery({ queryKey: ['alerts/gaps'], queryFn: getAlertGaps })

const dropRef = (data, ref) => {
  if (Array.isArray(data)) return data.filter((r) => r.record_ref !== ref)
  if (data?.items) {
    return { ...data, items: data.items.filter((r) => r.record_ref !== ref), total: Math.max(0, (data.total ?? data.items.length) - 1) }
  }
  return data
}

export const useDecision = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ ref, decision }) => postDecision(ref, decision),
    onMutate: async ({ ref }) => {
      await qc.cancelQueries({ queryKey: ['review'] })
      await qc.cancelQueries({ queryKey: ['review/paged'] })
      const prev = [
        ...qc.getQueriesData({ queryKey: ['review'] }),
        ...qc.getQueriesData({ queryKey: ['review/paged'] }),
      ]
      prev.forEach(([key, data]) => qc.setQueryData(key, dropRef(data, ref)))
      return { prev }
    },
    onError: (_err, _vars, context) => {
      context?.prev?.forEach(([key, data]) => qc.setQueryData(key, data))
    },
    onSettled: () => {
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
      qc.invalidateQueries({ queryKey: ['system/status'] })
    },
  })
}

export const useAckEvent = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }) => patchEvent(id, { resolution_status: status }),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: ['event', id] })
      qc.invalidateQueries({ queryKey: ['events'] })
    },
  })
}

export const useFlagAsset = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reviewStatus }) => patchAsset(id, { review_status: reviewStatus }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assets'] })
    },
  })
}
