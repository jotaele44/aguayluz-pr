import { useQuery } from '@tanstack/react-query'
import { getWaterUseEstimates } from '@/lib/water-use-api'

// Five-yearly publications that change only when a person re-runs the producer: no polling.
export const useWaterUseEstimates = () => useQuery({
  queryKey: ['water-use', 'estimates'],
  queryFn: getWaterUseEstimates,
  staleTime: Infinity,
})
