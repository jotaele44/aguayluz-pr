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
  summaryData = { municipality: 'Adjuntas', asset_count: 0, active_assets: 0, event_count: 0, asset_types: [], monitoring: [], flood_document: null }
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

  it('renders a frozen offline flood-document fallback with provenance', () => {
    summaryData = {
      ...summaryData,
      municipality: 'Quebradillas',
      flood_document: {
        municipality: 'Quebradillas',
        source_state: 'LISTED_BUT_MISSING',
        operational_document_class: 'hazard_mitigation_plan',
        operational_access_mode: 'frozen_local_manifestation',
        operational_source_url: null,
        provenance_fallback_source_url: 'https://example.test/quebradillas-hmp.pdf',
        fallback_relationship: 'authoritative_fallback_not_equivalent',
        filename: 'Quebradillas.pdf',
        sha256: 'a1a2ccbfe0097da6f531e78f834d01be5a1555700b809d8f68b162db83d23e7a',
        byte_size: 51199142,
        byte_certification: {
          certification_state: 'PASS',
          counts: {
            municipality_denominator: 78,
            byte_verified_count: 78,
            failure_count: 0,
          },
        },
      },
    }

    renderAt('Quebradillas')

    expect(screen.getByText('Flood Risk Document')).toBeInTheDocument()
    expect(screen.getByText(/Listed · source file missing/)).toBeInTheDocument()
    expect(screen.getByText(/hazard mitigation plan/)).toBeInTheDocument()
    expect(screen.getByText(/frozen local manifestation/)).toBeInTheDocument()
    expect(screen.getByText(/SHA256 a1a2ccbfe0097da6/)).toBeInTheDocument()
    expect(screen.getByText(/Byte certified 78\/78/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open document/i })).toHaveAttribute(
      'href',
      expect.stringContaining('/municipios/Quebradillas/flood-document/file'),
    )
    expect(screen.getByRole('link', { name: /Source provenance/i })).toHaveAttribute(
      'href',
      'https://example.test/quebradillas-hmp.pdf',
    )
  })

  it('keeps AVAILABLE distinct from byte certification', () => {
    summaryData = {
      ...summaryData,
      flood_document: {
        municipality: 'Adjuntas',
        source_state: 'AVAILABLE',
        operational_document_class: 'flood_risk_zone_map',
        operational_access_mode: 'local_cache_or_remote_fetch',
        filename: 'Adjuntas_sectores_inundables.pdf',
        sha256: '73e64bd18eef5cd0746f3d3537098024348c16b31cef2287a073c0595814ee8f',
        byte_size: 8766921,
        byte_certification: {
          certification_state: 'PASS',
          counts: { municipality_denominator: 78, byte_verified_count: 78, failure_count: 0 },
        },
      },
    }

    renderAt('Adjuntas')

    expect(screen.getByText('Available')).toBeInTheDocument()
    expect(screen.getByText(/Byte certified 78\/78/)).toBeInTheDocument()
    expect(screen.queryByText(/Listed · source file missing/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Not listed in source series/)).not.toBeInTheDocument()
  })

  it('keeps Florida NOT_LISTED distinct from byte certification', () => {
    summaryData = {
      ...summaryData,
      municipality: 'Florida',
      flood_document: {
        municipality: 'Florida',
        source_state: 'NOT_LISTED',
        operational_document_class: 'hazard_mitigation_plan',
        operational_access_mode: 'remote_fetch',
        operational_source_url: 'https://example.test/florida-hmp.pdf',
        fallback_relationship: 'authoritative_fallback_not_equivalent',
        filename: 'Flor-Plan-Approved-HMP.pdf',
        sha256: 'cfd9695995f721be9850e4e04c415f965f66e3eb48450d234ea2d9d15eb96f83',
        byte_size: 37883767,
        byte_certification: {
          certification_state: 'PASS',
          counts: { municipality_denominator: 78, byte_verified_count: 78, failure_count: 0 },
        },
      },
    }

    renderAt('Florida')

    expect(screen.getByText(/Not listed in source series/)).toBeInTheDocument()
    expect(screen.getByText(/Byte certified 78\/78/)).toBeInTheDocument()
    expect(screen.queryByText(/^Available$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Listed · source file missing/)).not.toBeInTheDocument()
  })

  it('does not throw and shows the empty state for a municipio name typed as a prototype key', () => {
    // Same class of hazard SectorDetailPage.test.jsx pins for :sector — the
    // municipio name comes straight from the URL here too.
    expect(() => renderAt('__proto__')).not.toThrow()
    expect(screen.getByText(/No monitoring stations in this municipio/i)).toBeInTheDocument()
  })
})
