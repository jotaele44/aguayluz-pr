import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import MunicipioDetailPage from '@/pages/MunicipioDetailPage'

// The monitoring section reads `summary.monitoring` — raw readings the backend
// joins per-municipio (server/backend/app.py `_monitoring_readings_for_assets`)
// — and maps them onto dashboard/src/lib/monitoring.js's MONITORING_SERIES the
// same way MonitoringCharts.jsx does. These tests pin that mapping, the drought
// D-category color treatment, and the empty-municipio state.

let summaryData
let eventsData

vi.mock('@/lib/hooks', () => ({
  useMunicipioSummary: () => ({ data: summaryData, isLoading: false }),
  useAssets: () => ({ data: [], isLoading: false }),
  useEventsPaged: () => ({ data: eventsData, isLoading: false }),
}))

const renderAt = (municipio) =>
  render(
    <MemoryRouter initialEntries={[`/municipios/${municipio}`]}>
      <Routes>
        <Route path="/municipios/:name" element={<MunicipioDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  summaryData = { municipality: 'Adjuntas', asset_count: 0, active_assets: 0, event_count: 0, asset_types: [], monitoring: [] }
  eventsData = { items: [], total: 0 }
})

describe('MunicipioDetailPage — monitoring section', () => {
  it('shows the empty state when the municipio has no monitoring stations', () => {
    renderAt('Adjuntas')

    expect(screen.getByText(/No monitoring stations in this municipio/i)).toBeInTheDocument()
  })

  it('renders a drought tile with the D-category label and count of stations for reservoir', () => {
    summaryData = {
      ...summaryData,
      monitoring: [
        { kind: 'drought', metric: 'drought_category', parameter_code: null, value: 2, unit: 'category', observed_date: '2026-08-16', site_no: '72001' },
        { kind: 'reservoir', metric: 'reservoir_elevation', parameter_code: '62615', value: 41.2, unit: 'ft', observed_date: '2026-08-20', site_no: 'A' },
        { kind: 'reservoir', metric: 'reservoir_elevation', parameter_code: '62615', value: 39.8, unit: 'ft', observed_date: '2026-08-19', site_no: 'B' },
      ],
    }

    renderAt('Adjuntas')

    expect(screen.getByText(/D2 · Severe drought/)).toBeInTheDocument()
    expect(screen.getByText(/41.2 ft/)).toBeInTheDocument()
    expect(screen.getByText(/2 stations/)).toBeInTheDocument()
    expect(screen.queryByText(/No monitoring stations/i)).not.toBeInTheDocument()
  })

  it('rolls up boil_water and water_quality_violation events into the Contamination stat', () => {
    eventsData = {
      total: 3,
      items: [
        { event_id: '1', event_type: 'water_quality_violation', municipality: 'Adjuntas' },
        { event_id: '2', event_type: 'boil_water', municipality: 'Adjuntas' },
        // Resolved (has end_time) — must not count toward the "active" tally.
        { event_id: '3', event_type: 'boil_water', municipality: 'Adjuntas', end_time: '2026-08-01' },
      ],
    }

    renderAt('Adjuntas')

    const card = screen.getByText('Contamination').closest('.fd-stat-card')
    expect(card).not.toBeNull()
    expect(card.querySelector('.fd-stat-card__value')).toHaveTextContent('2')
  })

  it('does not throw and shows the empty state for a municipio name typed as a prototype key', () => {
    // Same class of hazard SectorDetailPage.test.jsx pins for :sector — the
    // municipio name comes straight from the URL here too.
    expect(() => renderAt('__proto__')).not.toThrow()
    expect(screen.getByText(/No monitoring stations in this municipio/i)).toBeInTheDocument()
  })
})
