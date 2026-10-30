import { API_BASE } from '@/lib/api'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

async function getJSON(path) {
  if (OFFLINE) return null
  const response = await fetch(`${API_BASE}${path}`, {
    signal: AbortSignal.timeout(8000),
  })
  if (!response.ok) {
    throw new Error(`Food resilience request failed: ${response.status}`)
  }
  return response.json()
}

export const getFoodResilienceView = () => getJSON('/food-resilience/view')
export const getFoodResilienceState = () => getJSON('/food-resilience/state')
export const getFoodResilienceDependencies = () => getJSON('/food-resilience/dependencies')
export const getFoodResilienceSignals = () => getJSON('/food-resilience/phase1/signals')
export const getFoodResilienceBaseline = () => getJSON('/food-resilience/baseline')
export const getFoodResilienceScenarios = () => getJSON('/food-resilience/scenarios')
