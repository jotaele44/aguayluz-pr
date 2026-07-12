import { useQuery } from '@tanstack/react-query'
import {
  getMycelialGridGeojson,
  getMycelialObservations,
  getMycelialObservationsGeojson,
  getMycelialSummary,
} from '@/lib/api'

export const useMycelialSummary = () => useQuery({
  queryKey: ['mycelial-summary'],
  queryFn: getMycelialSummary,
})

export const useMycelialObservations = (f = {}) => useQuery({
  queryKey: ['mycelial-observations', f],
  queryFn: () => getMycelialObservations(f),
})

export const useMycelialObservationsGeojson = () => useQuery({
  queryKey: ['mycelial-observations.geojson'],
  queryFn: getMycelialObservationsGeojson,
})

export const useMycelialGridGeojson = () => useQuery({
  queryKey: ['mycelial-grid.geojson'],
  queryFn: getMycelialGridGeojson,
})
