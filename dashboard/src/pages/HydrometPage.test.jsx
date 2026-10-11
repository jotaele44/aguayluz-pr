import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import HydrometPage from '@/pages/HydrometPage'
import {
  getHydrometSources,
  getHydrometSummary,
  getRainfall,
  getRiverGauges,
  postHydrometRefresh,
} from '@/lib/hydromet-api'
import { getApiKey } from '@/lib/api'

vi.mock('@/lib/hydromet-api', () => ({
  getHydrometSummary: vi.fn(),
  getHydrometSources: vi.fn(),
  getRainfall: vi.fn(),
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

// Mayagüez is CONSTRUCTED to cross the heavy-rain threshold; Aguada is the real
// 2026-10-09 Stage IV summary.
const RAINFALL = {
  window: '1day',
  window_days: 1,
  windows: ['1day', 'last7days', 'last30days'],
  data_date: '2026-10-09',
  available_dates: ['2026-10-09', '2026-10-08'],
  thresholds: { mean_in: 3, cell_max_in: 6, applies_to: '1day' },
  files: [{
    manifestation_id: 'HYDROMET:stage_iv_pr:8ad7d7b0793ea1e3b422b1af26fd163a',
    source_record_id: 'nws_precip_1day_20261009_pr.tif',
    source_url: 'https://water.noaa.gov/resources/downloads/precip/stageIV/2026/10/09/nws_precip_1day_20261009_pr.tif',
    byte_sha256: '8ad7d7b0793ea1e3b422b1af26fd163a1a1213c3b754995eaa2d2c46ecd738eb',
    retrieved_at: '2026-10-11T04:12:00Z',
  }],
  total: 2,
  items: [
    { geoid: '72097', municipio: 'Mayagüez', obs_mean_in: 3.4, obs_max_in: 4.2, normal_mean_in: 0.3, pct_of_normal: 1133.3, cell_count: 12, method: 'raster_cell_centres_in_polygon', heavy_rain_severity: 2, record_id: 'r1' },
    { geoid: '72003', municipio: 'Aguada', obs_mean_in: 1.064, obs_max_in: 1.606, normal_mean_in: 0.278, pct_of_normal: 382.3, cell_count: 9, method: 'raster_cell_centres_in_polygon', heavy_rain_severity: null, record_id: 'r2' },
  ],
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
  getRainfall.mockResolvedValue(RAINFALL)
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

  it('ranks municipio rainfall with heavy-rain flags and file provenance', async () => {
    renderPage()
    const table = await screen.findByRole('table', { name: 'Stage IV rainfall by municipio' })
    expect(table).toHaveTextContent('Mayagüez')
    expect(table).toHaveTextContent('3.40 in')
    expect(table).toHaveTextContent('severity 2')
    expect(screen.getByRole('link', { name: 'Aguada' })).toHaveAttribute('href', '/municipios/Aguada')
    expect(screen.getByTestId('rainfall-provenance')).toHaveTextContent('1 at a heavy-rain threshold')
    expect(screen.getByTestId('rainfall-provenance')).toHaveTextContent('SHA-256 8ad7d7b0793ea1e3')
    expect(screen.getByText(/any cell ≥ 6 in \(severity 3\)/)).toBeInTheDocument()
  })

  it('switches rainfall window and data day', async () => {
    renderPage()
    await screen.findByRole('table', { name: 'Stage IV rainfall by municipio' })
    fireEvent.change(screen.getByRole('combobox', { name: 'Rainfall data day' }), { target: { value: '2026-10-08' } })
    await waitFor(() => expect(getRainfall).toHaveBeenCalledWith({ window: '1day', date: '2026-10-08' }))
    fireEvent.click(screen.getByRole('button', { name: '7 days' }))
    await waitFor(() => expect(getRainfall).toHaveBeenCalledWith({ window: 'last7days', date: undefined }))
    expect(screen.getByRole('button', { name: '7 days' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('explains an empty rainfall plane', async () => {
    getRainfall.mockResolvedValue({ ...RAINFALL, data_date: null, available_dates: [], files: [], total: 0, items: [] })
    renderPage()
    expect(await screen.findByText(/No Stage IV rainfall ingested yet/)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderPage()
    await screen.findByText('Lago Guajataca at Damsite')
    await screen.findByRole('table', { name: 'Stage IV rainfall by municipio' })
    expect(await axe(container)).toHaveNoViolations()
  })
})
