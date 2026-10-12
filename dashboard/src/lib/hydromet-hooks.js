import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getHydrometSources,
  getHydrometSummary,
  getRiverGauges,
  getRiverGaugesGeojson,
  postHydrometRefresh,
} from '@/lib/hydromet-api'

// Gauge state moves every 15 minutes upstream; poll a little slower than that.
const GAUGE_REFETCH_MS = 5 * 60_000

export const useHydrometSummary = () => useQuery({
  queryKey: ['hydromet', 'summary'],
  queryFn: getHydrometSummary,
  refetchInterval: GAUGE_REFETCH_MS,
})

export const useHydrometSources = () => useQuery({
  queryKey: ['hydromet', 'sources'],
  queryFn: getHydrometSources,
  refetchInterval: GAUGE_REFETCH_MS,
})

export const useRiverGauges = (filters = {}) => useQuery({
  queryKey: ['hydromet', 'gauges', filters],
  queryFn: () => getRiverGauges(filters),
  refetchInterval: GAUGE_REFETCH_MS,
})

export const useRiverGaugesGeojson = () => useQuery({
  queryKey: ['hydromet', 'gauges.geojson'],
  queryFn: getRiverGaugesGeojson,
  refetchInterval: GAUGE_REFETCH_MS,
})

export const useHydrometRefresh = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: postHydrometRefresh,
    // A failed run still writes a FAIL receipt, so refetch either way.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['hydromet'] })
      qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
}
