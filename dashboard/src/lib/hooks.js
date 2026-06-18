import { useQuery } from '@tanstack/react-query'
import {
  getHealth, getAssets, getAssetsGeojson, getMunicipiosGeojson,
  getEvents, getReadings, getReviewQueue, getSummary,
} from '@/lib/api'

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 15_000 })
export const useSummary = () => useQuery({ queryKey: ['summary'], queryFn: getSummary })
export const useAssets = (f = {}) => useQuery({ queryKey: ['assets', f], queryFn: () => getAssets(f) })
export const useAssetsGeojson = () => useQuery({ queryKey: ['assets.geojson'], queryFn: getAssetsGeojson })
export const useMunicipiosGeojson = () => useQuery({ queryKey: ['municipios.geojson'], queryFn: getMunicipiosGeojson })
export const useEvents = () => useQuery({ queryKey: ['events'], queryFn: () => getEvents() })
export const useReadings = (kind) => useQuery({ queryKey: ['readings', kind], queryFn: () => getReadings(kind) })
export const useReviewQueue = () => useQuery({ queryKey: ['review'], queryFn: getReviewQueue })
