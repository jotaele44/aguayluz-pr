import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import HydrometPage from '@/pages/HydrometPage'
import {
  getHydrometSources,
  getHydrometSummary,
  getRiverGauges,
  postHydrometRefresh,
} from '@/lib/hydromet-api'
import { getApiKey } from '@/lib/api'

vi.mock('@/lib/hydromet-api', () => ({
  getHydrometSummary: vi.fn(),
  getHydrometSources: vi.fn(),
  getRiverGauges: vi.fn(),
  getRiverGaugesGeojson: vi.fn(),
  postHydrometRefresh: vi.fn(),
}))

const systemStatus = { auth_enabled: false }
vi.mock('@/lib/hooks', () => ({
  useHealth: () => ({ data: { status: 'ok' }, isError: false }),
  useSystemStatus: () => ({ data: systemStatus }),
}))

vi.mock('@/lib/api', () => ({ getApiKey: vi.fn(() => '') }))

// Shapes mirror server/backend/hydromet_api.py responses for the real QUEP4 capture.
const SOURCE = {
  source_id: 'nwps_gauges',
  label: 'NWPS river gauges (flood status)',
  authority: 'NOAA/NWS National Water Prediction Service',
  cadence_seconds: 900,
  max_age_seconds: 7200,
  endpoints: { gauges: 'https://api.water.noaa.gov/nwps/v1/gauges' },
  known_limits: 'Observed stages only.',
  freshness: { state: 'FRESH', age_seconds: 600, max_age_seconds: 7200 },
  receipt: {
    last_status: 'PASS',
    last_attempt_utc: '2026-10-07T20:00:00Z',
    last_success_utc: '2026-10-07T20:00:00Z',
    last_error: null,
    last_success: {
      byte_sha256: 'bdfaa33c916724e52751dd9ff99c63a8f0602d0d69bfb7802125b09a25ccbd5a',
      source_url: 'https://api.water.noaa.gov/nwps/v1/gauges',
      arithmetic: { source: 118, retained: 118, excluded: 0, unresolved: 0, state: 'PASS' },
    },
  },
}

const GAUGE = {
  lid: 'QUEP4',
  name: 'Lago Guajataca at Damsite',
  usgs_id: '50010800',
  asset_id: 'USGS_50010800',
  municipio: 'Quebradillas',
  binding_evidence: 'POINT_IN_POLYGON_WITH_ALIAS',
  flood_category: 'minor',
  observed: { stage: 654.4, stage_unit: 'ft', valid_time: '2026-10-07T18:45:00Z' },
  observation_stale: false,
  thresholds: { action: { stage: 644.0 }, minor: { stage: 644.6 } },
  threshold_stage_unit: 'ft',
  latitude: 18.47,
  longitude: -66.92,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HydrometPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  systemStatus.auth_enabled = false
  getApiKey.mockReturnValue('')
  getHydrometSummary.mockResolvedValue({
    scope: { statement: 'Observed hazard condition, not confirmed damage.' },
    counts: { gauges: 118, gauges_in_flood: 1, gauges_stale: 1 },
    integrity: { state: 'PASS', unresolved: [] },
  })
  getHydrometSources.mockResolvedValue({ sources: [SOURCE] })
  getRiverGauges.mockResolvedValue({ total: 1, items: [GAUGE] })
  postHydrometRefresh.mockResolvedValue({ ok: true, receipt: SOURCE.receipt })
})

describe('HydrometPage', () => {
  it('shows source freshness, provenance and the gauge in flood', async () => {
    renderPage()
    expect(await screen.findByText('Lago Guajataca at Damsite')).toBeInTheDocument()
    expect(screen.getByText('FRESH')).toBeInTheDocument()
    expect(screen.getByText(/118 source = 118 retained \+ 0 excluded \+ 0 unresolved/)).toBeInTheDocument()
    expect(screen.getByText(SOURCE.receipt.last_success.byte_sha256)).toBeInTheDocument()
    expect(screen.getByText('minor')).toBeInTheDocument()
    expect(screen.getByText('Observed hazard condition, not confirmed damage.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'USGS_50010800' })).toHaveAttribute(
      'href', expect.stringContaining('/map?flyTo=USGS_50010800'),
    )
  })

  it('runs a refresh for the source', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /refresh now/i }))
    await waitFor(() => expect(postHydrometRefresh).toHaveBeenCalled())
    expect(postHydrometRefresh.mock.calls[0][0]).toBe('nwps_gauges')
  })

  it('filters to gauges in flood', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /show only gauges in flood/i }))
    await waitFor(() => expect(getRiverGauges).toHaveBeenCalledWith({ flooding_only: true }))
  })

  it('disables refresh when the backend needs a key that is not set', async () => {
    systemStatus.auth_enabled = true
    renderPage()
    expect(await screen.findByRole('button', { name: /refresh now/i })).toBeDisabled()
    expect(screen.getByText(/API_SECRET_KEY is set on the backend/)).toBeInTheDocument()
  })

  it('surfaces a failed latest attempt', async () => {
    getHydrometSources.mockResolvedValue({
      sources: [{
        ...SOURCE,
        freshness: { state: 'FAILED', age_seconds: 900, max_age_seconds: 7200 },
        receipt: { ...SOURCE.receipt, last_status: 'FAIL', last_error: 'bulk fetch failed: timeout' },
      }],
    })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('bulk fetch failed: timeout')
    expect(screen.getByText('FAILED')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderPage()
    await screen.findByText('Lago Guajataca at Damsite')
    expect(await axe(container)).toHaveNoViolations()
  })
})
