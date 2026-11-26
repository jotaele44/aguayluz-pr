import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import IonospherePage from './IonospherePage'

vi.mock('@/lib/api', () => ({ API_BASE: '' }))
afterEach(() => vi.unstubAllGlobals())
it('shows request failure and supports retry without claiming no observations', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
  render(<QueryClientProvider client={new QueryClient()}><IonospherePage /></QueryClientProvider>)
  expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503')
  fireEvent.click(screen.getByRole('button', { name: 'Retry / Reintentar' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('unavailable')
})
it('renders blocked provenance and unresolved ROTI', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    state: 'BLOCKED', freshness: 'NEVER', tec: { state: 'BLOCKED', reason: 'HTTP 403', resolution_degrees: [2.5, 5] },
    roti: { state: 'UNRESOLVED', reason: 'Coverage unverified' },
    acquisition_attempt: { date: '2026-10-23', http_status: 403 }, source_url: 'https://www.spaceweather.gov/products/glotec',
  }) }))
  render(<QueryClientProvider client={new QueryClient()}><IonospherePage /></QueryClientProvider>)
  expect(await screen.findByRole('region', { name: 'Ionosphere source audit' })).toHaveTextContent('UNRESOLVED')
  expect(screen.getByRole('link', { name: 'NOAA source documentation' })).toHaveAttribute('href', 'https://www.spaceweather.gov/products/glotec')
})
it('shows archived values, model scope and provenance without treating them as live', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    state: 'BLOCKED', freshness: 'NEVER', tec: { state: 'ARCHIVED_SNAPSHOT', reason: 'Frozen capture', resolution_degrees: [2.5, 5] },
    roti: { state: 'UNRESOLVED', reason: 'Coverage unverified' },
    acquisition_attempt: { date: '2026-10-23', http_status: 403 }, source_url: 'https://www.spaceweather.gov/products/glotec',
    archive: { state: 'ARCHIVED_SNAPSHOT', freshness: 'STALE', observed_at: '2026-10-23T16:35:00Z',
      selected_count: 1, excluded_count: 0, total_features: 1, source_sha256: 'a'.repeat(64),
      source_url: 'https://example.org/synthetic-test', rows: [{ source_feature_index: 0, longitude: -67.5, latitude: 18.75, raw_feature: { properties: { tec: 0, quality_flag: 0 } } }] },
  }) }))
  render(<QueryClientProvider client={new QueryClient()}><IonospherePage /></QueryClientProvider>)
  const region = await screen.findByRole('region', { name: 'Archived TEC context' })
  expect(region).toHaveTextContent('STALE')
  expect(region).toHaveTextContent('not municipality measurements')
  expect(screen.getByRole('table', { name: 'Archived TEC grid points' })).toBeVisible()
  expect(region).toHaveTextContent('Source SHA-256:')
})
