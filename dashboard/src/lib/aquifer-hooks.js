import { useQuery } from '@tanstack/react-query'
import { getAquiferBands } from '@/lib/aquifer-api'

// Depth readings arrive every 15 minutes upstream; the bands change at most weekly. Polling
// at the reading cadence keeps the class current without hammering a static registry.
const REFETCH_MS = 5 * 60_000

export const useAquiferBands = () => useQuery({
  queryKey: ['aquifer', 'bands'],
  queryFn: getAquiferBands,
  refetchInterval: REFETCH_MS,
})
