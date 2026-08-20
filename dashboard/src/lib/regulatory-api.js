import { API_BASE } from '@/lib/api'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

async function getJSON(path, fallback) {
  if (OFFLINE) return fallback
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      signal: AbortSignal.timeout(8000),
    })
    if (!response.ok) return fallback
    return await response.json()
  } catch {
    return fallback
  }
}

const qs = (params) => {
  const pairs = Object.entries(params).filter(([, value]) => value != null && value !== '')
  return pairs.length ? `?${new URLSearchParams(pairs).toString()}` : ''
}

export const getRegulatorySummary = () => getJSON('/regulatory/summary', null)

export const getRegulatoryObservations = (filters = {}) => getJSON(
  `/regulatory/observations${qs(filters)}`,
  { total: 0, items: [] },
)

export const getRegulatoryObservation = (observationId) => getJSON(
  `/regulatory/observations/${encodeURIComponent(observationId)}`,
  null,
)

export const getRegulatoryReceipt = (receiptId) => getJSON(
  `/regulatory/receipts/${encodeURIComponent(receiptId)}`,
  null,
)
