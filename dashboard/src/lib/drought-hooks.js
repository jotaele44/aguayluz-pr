import { useQuery } from '@tanstack/react-query'
import {
  getDroughtAlertsGeojson,
  getDroughtFootprint,
  getDroughtOutageEvents,
  getDroughtOutageStatus,
  getDroughtReservoirReadings,
  getDroughtSummary,
} from '@/lib/drought-api'

const WEEKLY_CHECK_MS = 30 * 60_000
const RESERVOIR_CHECK_MS = 15 * 60_000
const INCIDENT_CHECK_MS = 60_000

export const useDroughtSummary = () => useQuery({
  queryKey: ['drought-operations', 'summary'],
  queryFn: getDroughtSummary,
  refetchInterval: WEEKLY_CHECK_MS,
})

export const useDroughtFootprint = () => useQuery({
  queryKey: ['drought-operations', 'footprint'],
  queryFn: getDroughtFootprint,
  refetchInterval: WEEKLY_CHECK_MS,
})

export const useDroughtReservoirReadings = () => useQuery({
  queryKey: ['drought-operations', 'reservoir-readings'],
  queryFn: getDroughtReservoirReadings,
  refetchInterval: RESERVOIR_CHECK_MS,
})

export const useDroughtAlertsGeojson = () => useQuery({
  queryKey: ['drought-operations', 'alerts'],
  queryFn: getDroughtAlertsGeojson,
  refetchInterval: INCIDENT_CHECK_MS,
})

export const useDroughtOutageEvents = () => useQuery({
  queryKey: ['drought-operations', 'outage-events'],
  queryFn: getDroughtOutageEvents,
  refetchInterval: INCIDENT_CHECK_MS,
})

export const useDroughtOutageStatus = () => useQuery({
  queryKey: ['drought-operations', 'outage-status'],
  queryFn: getDroughtOutageStatus,
  refetchInterval: INCIDENT_CHECK_MS,
})
