import { API_BASE, getApiKey } from './api'

async function request(path, body) {
  if (import.meta.env.VITE_OFFLINE === '1') throw new Error('ELECTRICITY_OFFLINE_UNAVAILABLE')
  const key = getApiKey()
  const response = await fetch(`${API_BASE}/electricity/v1/${path}`, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json', ...(key ? { Authorization: `Bearer ${key}` } : {}) } : {},
    ...(body ? { body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(body ? 180000 : 15000),
  })
  if (!response.ok) throw new Error(`ELECTRICITY_HTTP_${response.status}`)
  return response.json()
}

export const getElectricityProjection = () => request('projection')
export const getElectricityReviews = () => request('reviews')
export const appendElectricityReview = (body) => request('reviews', body)
export const getElectricityJobs = (offset = 0) => request(`acquisition-jobs?offset=${offset}&limit=20`)
export const createElectricityJob = (body) => request('acquisition-jobs', body)
export const stepElectricityJob = (id, expected_version) => request(`acquisition-jobs/${id}/step`, { expected_version })
export const cancelElectricityJob = (id, expected_version) => request(`acquisition-jobs/${id}/cancel`, { expected_version })
export const acquireElectricityWorkbook = (url) => request('acquire', { url })
export const importElectricityWorkbook = (body) => request('import/860m', body)

export async function uploadElectricityWorkbook(file, sourceUrl) {
  if (import.meta.env.VITE_OFFLINE === '1') throw new Error('ELECTRICITY_OFFLINE_UNAVAILABLE')
  if (!file || file.size > 50000000) throw new Error('EIA_FILE_SIZE_INVALID')
  const key = getApiKey()
  const response = await fetch(`${API_BASE}/electricity/v1/import/workbook`, {
    method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream', 'X-EIA-Source-URL': sourceUrl, ...(key ? { Authorization: `Bearer ${key}` } : {}) },
    signal: AbortSignal.timeout(60000),
  })
  if (!response.ok) throw new Error(`ELECTRICITY_HTTP_${response.status}`)
  return response.json()
}
