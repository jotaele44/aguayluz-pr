import { fireEvent, render, screen } from '@testing-library/react'
import { forwardRef, useImperativeHandle } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DroughtPage from '@/pages/DroughtPage'

const exportSnapshot = vi.fn()
const query = (data) => ({ data, isFetching: false, refetch: vi.fn() })

vi.mock('@/components/DroughtMap', () => ({
  default: forwardRef(function MockDroughtMap(props, ref) {
    useImperativeHandle(ref, () => ({ exportSnapshot }))
    return (
      <div data-testid="drought-map">
        <button type="button" onClick={() => props.onMunicipioSelect({ name: 'Lajas', geoid: '72079' })}>
          Select Lajas
        </button>
        <button type="button" onClick={() => props.onFootprintSelect({ category: 'D3' })}>
          Select D3
        </button>
      </div>
    )
  }),
}))

const summary = {
  status: 'available',
  map_date: '2026-10-13',
  retrieved_at: '2026-10-15T10:00:00Z',
  authority: 'NDMC/USDM (USDA/NOAA/NASA partnership)',
  freshness: { state: 'FRESH', age_days: 2, max_age_days: 10 },
  statistics: {
    map_date: '2026-10-13',
    None: 36,
    D0: 64,
    D1: 48,
    D2: 28,
    D3: 9,
    D4: 0,
    semantics: 'cumulative_percent_area_at_or_above_category',
  },
  history: [
    { map_date: '2026-10-06', D0: 61, D1: 43, D2: 24, D3: 5, D4: 0 },
    { map_date: '2026-10-13', D0: 64, D1: 48, D2: 28, D3: 9, D4: 0 },
  ],
  change: {
    from_map_date: '2026-10-06',
    to_map_date: '2026-10-13',
    direction: 'worsened',
    delta_percentage_points: { D0: 3, D1: 5, D2: 4, D3: 4, D4: 0 },
    basis: 'descriptive only',
  },
  municipio_date: '2026-10-13',
  municipios: [
    { geoid: '72079', municipio: 'Lajas', category: 'D3', observed_date: '2026-10-13' },
    { geoid: '72113', municipio: 'Ponce', category: 'D3', observed_date: '2026-10-13' },
    { geoid: '72127', municipio: 'San Juan', category: 'D1', observed_date: '2026-10-13' },
  ],
  source_manifestations: {
    geometry: { sha256: 'a'.repeat(64) },
    statistics: { sha256: 'b'.repeat(64) },
  },
}

vi.mock('@/lib/drought-hooks', () => ({
  useDroughtSummary: vi.fn(() => query(summary)),
  useDroughtFootprint: vi.fn(() => query({
    type: 'FeatureCollection',
    status: 'available',
    features: [{ type: 'Feature', properties: { category: 'D3' }, geometry: { type: 'Polygon', coordinates: [] } }],
  })),
  useDroughtReservoirReadings: vi.fn(() => query([{ observed_date: '2026-10-14' }])),
  useDroughtAlertsGeojson: vi.fn(() => query({ type: 'FeatureCollection', features: [{ properties: {} }] })),
  useDroughtOutageEvents: vi.fn(() => query([{ event_id: 'e1', lat: 18.1, lon: -66.4 }, { event_id: 'e2' }])),
  useDroughtOutageStatus: vi.fn(() => query({
    latest: { snapshot_ts: '2026-10-15T16:00:00Z' },
    schema_state: 'RAW_UNFROZEN',
  })),
}))

vi.mock('@/lib/hooks', () => ({
  useAssetsGeojson: vi.fn(() => query({ type: 'FeatureCollection', features: [] })),
  useMunicipiosGeojson: vi.fn(() => query({ type: 'FeatureCollection', features: [] })),
}))

vi.mock('@/lib/hydromet-hooks', () => ({
  useRainfall: vi.fn(() => query({
    data_date: '2026-10-14',
    items: [{ geoid: '72079', obs_mean_in: 0.1 }],
  })),
  useRiverGaugesGeojson: vi.fn(() => query({
    type: 'FeatureCollection',
    features: [{ properties: { valid_time: '2026-10-15T16:30:00Z' } }],
  })),
}))

describe('DroughtPage', () => {
  beforeEach(() => exportSnapshot.mockClear())

  it('shows the official cumulative status, change and source guardrails', () => {
    render(<DroughtPage />)
    expect(screen.getByText('Puerto Rico Drought Operations')).toBeInTheDocument()
    expect(screen.getByText('64%')).toBeInTheDocument()
    expect(screen.getByText('48%')).toBeInTheDocument()
    expect(screen.getByText('28%')).toBeInTheDocument()
    expect(screen.getByText('9%')).toBeInTheDocument()
    expect(screen.getByText(/Percentages are cumulative area shares/)).toBeInTheDocument()
    expect(screen.getByText('worsened')).toBeInTheDocument()
    expect(screen.getByText(/No authoritative geospatial rationing feed/)).toBeInTheDocument()
    expect(screen.getByText('RAW_UNFROZEN', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument()
  })

  it('pivots the intelligence rail from map selection and exports a briefing PNG', () => {
    render(<DroughtPage />)
    fireEvent.click(screen.getByRole('button', { name: 'Select Lajas' }))
    expect(screen.getByText('Lajas')).toBeInTheDocument()
    expect(screen.getByText(/Municipio classification:/)).toHaveTextContent('D3')
    fireEvent.click(screen.getByRole('button', { name: 'Select D3' }))
    expect(screen.getByText(/Selected footprint:/)).toHaveTextContent('D3')
    fireEvent.click(screen.getByRole('button', { name: 'Export PNG' }))
    expect(exportSnapshot).toHaveBeenCalledTimes(1)
  })
})
