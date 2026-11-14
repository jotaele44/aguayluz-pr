import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import GridStatusPage from './GridStatusPage'
import { getGridStatus } from '@/lib/api'

vi.mock('@/lib/api', () => ({ getGridStatus: vi.fn() }))

const renderPage = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><GridStatusPage /></MemoryRouter>
  </QueryClientProvider>,
)

describe('GridStatusPage fail-closed observability', () => {
  beforeEach(() => vi.resetAllMocks())

  it('does not replace absent measurements with zero or a live claim', async () => {
    getGridStatus.mockResolvedValue({
      status: 'STALE',
      source: { family: 'LUMA_OUTAGES', observation_at: '2026-08-30T10:00:00Z',
        schema_state: 'RAW_UNFROZEN', snapshot_count: 1, payload_sha256: 'a'.repeat(64) },
      measurements: {
        customers_without_service: null, demand_mw: null,
        available_supply_mw: null, reserve_mw: null, hydro_available_mw: null,
      },
      limitations: ['No live operating conditions are inferred'],
      release_certified: false,
    })
    renderPage()
    expect(await screen.findByText('STALE')).toBeTruthy()
    expect(screen.getAllByText('Unavailable')).toHaveLength(5)
    expect(screen.getByText(/WITHHELD/)).toBeTruthy()
    expect(screen.queryByText('0 MW')).toBeNull()
  })

  it('reports unavailable backend without fabricating current readings', async () => {
    getGridStatus.mockRejectedValue(new Error('offline'))
    renderPage()
    expect(await screen.findByText('SOURCE UNAVAILABLE')).toBeTruthy()
    expect(screen.getByText(/API could not be reached/)).toBeTruthy()
    expect(screen.getAllByText('Unavailable')).toHaveLength(5)
  })
})
