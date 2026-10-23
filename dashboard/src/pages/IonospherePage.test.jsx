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
