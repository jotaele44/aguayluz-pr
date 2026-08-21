import { API_BASE, getApiKey } from '@/lib/api'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

// Merged into the one write request this module makes (decide). Absent when no key
// is set, so a backend with auth disabled sees exactly the request it saw before.
// Mirrors dashboard/src/lib/api.js's authHeaders/jsonHeaders/authFailureMessage,
// which are module-private there.
const authHeaders = () => {
  const key = getApiKey()
  return key ? { Authorization: `Bearer ${key}` } : {}
}

const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...authHeaders() })

const authFailureMessage = () =>
  getApiKey()
    ? 'Rejected: the API key set in System & Tools is not accepted by this backend.'
    : 'Refused: API key auth is enabled on the backend. Set the key in System & Tools.'

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

export const getRegulatoryLinks = (filters = {}) => getJSON(
  `/regulatory/links${qs(filters)}`,
  { total: 0, items: [] },
)

export const getRegulatoryLink = (candidateId) => getJSON(
  `/regulatory/links/${encodeURIComponent(candidateId)}`,
  null,
)

// Not silently swallowed like the getters above: a decision the operator believes
// went through but didn't (auth rejected, contradictions blocked it) must surface,
// so this throws rather than returning a fallback.
export const postRegulatoryLinkDecision = async (candidateId, decisionState, actor, rationale) => {
  if (OFFLINE) return { ok: true }
  const res = await fetch(`${API_BASE}/regulatory/links/${encodeURIComponent(candidateId)}/decide`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ decision_state: decisionState, actor, rationale }),
    signal: AbortSignal.timeout(8000),
  })
  if (res.status === 401) throw new Error(`Decision ${authFailureMessage()}`)
  if (res.status === 422) {
    const body = await res.json().catch(() => null)
    const contradictions = body?.detail?.contradictions ?? []
    throw new Error(
      contradictions.length
        ? `Cannot approve: ${contradictions.map((c) => c.detail).join('; ')}`
        : 'Decision rejected: the candidate cannot be approved while contradictions remain open.',
    )
  }
  if (!res.ok) throw new Error(`Decision failed (${res.status})`)
  return res.json()
}
