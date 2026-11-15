import { useQuery } from '@tanstack/react-query'
import {
  getAquiferWells, getHydroCandidates, getHydroConflicts, getHydroFeature, getHydroFeatures, getHydroSummary,
} from '@/lib/hydro-inventory-api'

// The inventory changes only when a maintainer re-runs the ingests: no polling.
const STATIC = { staleTime: Infinity }

export const useHydroSummary = () => useQuery({ queryKey: ['hydro', 'summary'], queryFn: getHydroSummary, ...STATIC })
export const useHydroFeatures = (params, enabled = true) => useQuery({
  queryKey: ['hydro', 'features', params], queryFn: () => getHydroFeatures(params), enabled, ...STATIC,
})
export const useHydroFeature = (id) => useQuery({
  queryKey: ['hydro', 'feature', id], queryFn: () => getHydroFeature(id), enabled: Boolean(id), ...STATIC,
})
export const useHydroConflicts = (enabled = true) => useQuery({
  queryKey: ['hydro', 'conflicts'], queryFn: getHydroConflicts, enabled, ...STATIC,
})
export const useHydroCandidates = (params, enabled = true) => useQuery({
  queryKey: ['hydro', 'candidates', params], queryFn: () => getHydroCandidates(params), enabled, ...STATIC,
})
export const useAquiferWells = (aquifer, includePolygon) => useQuery({
  queryKey: ['hydro', 'aquifer-wells', aquifer, includePolygon],
  queryFn: () => getAquiferWells(aquifer, includePolygon),
  enabled: Boolean(aquifer),
  ...STATIC,
})
