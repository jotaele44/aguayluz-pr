import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CaveKarstPage from '@/pages/CaveKarstPage'
import {
  getCaveKarstAlerts,
  getCaveKarstAsset,
  getCaveKarstAssets,
  getCaveKarstEdges,
  getCaveKarstProvenance,
  getCaveKarstStatusHistory,
  getCaveKarstSummary,
} from '@/lib/cave-karst-api'

vi.mock('@/lib/cave-karst-api', () => ({
  getCaveKarstSummary: vi.fn(),
  getCaveKarstAssets: vi.fn(),
  getCaveKarstAsset: vi.fn(),
  getCaveKarstStatusHistory: vi.fn(),
  getCaveKarstProvenance: vi.fn(),
  getCaveKarstEdges: vi.fn(),
  getCaveKarstAlerts: vi.fn(),
}))

const ASSET = {
  asset_id: 'AYL_KARST_CAMUY_PARK',
  canonical_name: 'Parque Nacional de las Cavernas del Río Camuy',
  asset_kind: 'park',
  municipalities: ['Camuy'],
  current_status: 'closed',
  status_as_of: '2026-08-04T00:44:00Z',
  confidence: 85,
  evidence_tier: 'T2',
  review_status: 'accepted',
  location_disclosure: 'public_generalized',
  coordinates_redacted: true,
  freshness: { stale: false, age_days: 0, status_as_of: '2026-08-04T00:44:00Z' },
  unresolved_gaps: ['infrastructure_condition_unknown'],
  operational: { operator: 'Departamento de Recursos Naturales y Ambientales' },
  hydrologic: {
    roles: ['recharge', 'underground_channel'],
    flood_sensitivity: 'high',
    monitoring_status: 'unknown',
    surface_water_connection: 'confirmed',
  },
  infrastructure: {
    condition: 'unknown',
    emergency_access: 'unknown',
    power_dependency: 'supporting',
    components: ['visitor_center', 'trail'],
  },
  observations: [],
}

const SUMMARY = {
  scope: {
    statement: 'Río Camuy pilot registry only. This is not a complete Puerto Rico cave census.',
    statewide_complete: false,
    registry_scope: { pilot: 4 },
  },
  counts: {
    assets: 4,
    sources: 4,
    edges: 6,
    status_events: 3,
    observations: 2,
    alerts: 3,
    unresolved_gaps: 9,
  },
  validation: { ok: true, contradiction_count: 0, error_count: 0 },
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <CaveKarstPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getCaveKarstSummary.mockResolvedValue(SUMMARY)
  getCaveKarstAssets.mockResolvedValue({ total: 1, items: [ASSET] })
  getCaveKarstAsset.mockResolvedValue({ ...ASSET, alerts: [], edge_count: 1, source_count: 1 })
  getCaveKarstStatusHistory.mockResolvedValue({
    asset_id: ASSET.asset_id,
    total: 1,
    items: [{
      event_id: 'AYL_KEVT_CAMUY_CURRENT_CLOSED',
      event_type: 'closure_notice',
      to_status: 'closed',
      effective_from: '2026-08-04T00:44:00Z',
      evidence_tier: 'T2',
      review_status: 'accepted',
    }],
  })
  getCaveKarstProvenance.mockResolvedValue({
    asset_id: ASSET.asset_id,
    total: 1,
    evidence_policy: 'Claims remain bounded by evidence tier and review status.',
    items: [{
      source_id: 'SRC_KARST_DPR_CLOSED_20260803',
      title: 'Explora el Parque Nacional de las Cavernas del Río Camuy',
      publisher: 'Discover Puerto Rico',
      evidence_tier: 'T2',
      review_status: 'accepted',
      url: 'https://example.test/source',
      notes: 'Direct operator confirmation remains desirable.',
    }],
  })
  getCaveKarstEdges.mockResolvedValue({
    asset_id: ASSET.asset_id,
    total: 1,
    items: [{
      edge_id: 'AYL_KEDGE_CAMUY_PARK_CONTAINS_CLARA',
      relation: 'contains',
      direction: 'outbound',
      to_node_id: 'AYL_KARST_CAMUY_CUEVA_CLARA',
      confidence: 95,
    }],
  })
  getCaveKarstAlerts.mockResolvedValue({
    total: 1,
    items: [{
      alert_id: 'AYL_KALERT_CAMUY_PARK_ACCESS',
      asset_id: ASSET.asset_id,
      alert_type: 'public_access_restriction',
      severity: 3,
      summary: 'The park is closed.',
    }],
  })
})

describe('CaveKarstPage', () => {
  it('renders the pilot limitation and required analytical fields', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Cave & Karst Monitor' })).toBeInTheDocument()
    expect(screen.getByRole('note', { name: 'Registry scope limitation' })).toHaveTextContent(/pilot/i)
    expect(await screen.findByText(/not a complete puerto rico cave census/i)).toBeInTheDocument()
    expect((await screen.findAllByText(ASSET.canonical_name)).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('Closed')).length).toBeGreaterThan(0)
    expect(await screen.findByText('85%')).toBeInTheDocument()
    expect((await screen.findAllByText('T2')).length).toBeGreaterThan(0)
    expect(await screen.findByText(/Recharge, Underground Channel/i)).toBeInTheDocument()
    expect(await screen.findByText(/Infrastructure Condition Unknown/i)).toBeInTheDocument()
    expect(await screen.findByText(/precise coordinates are withheld/i)).toBeInTheDocument()
  })

  it('selects assets through accessible pressed buttons', async () => {
    renderPage()

    const button = await screen.findByRole('button', { name: new RegExp(ASSET.canonical_name) })
    await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'true'))
    expect(getCaveKarstAsset).toHaveBeenCalledWith(ASSET.asset_id)
  })

  it('renders provenance and graph evidence', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Provenance' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /open source/i })).toHaveAttribute(
      'href',
      'https://example.test/source',
    )
    expect(await screen.findByText('Contains')).toBeInTheDocument()
    expect(await screen.findByText(/severity 3/i)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderPage()
    expect((await screen.findAllByText(ASSET.canonical_name)).length).toBeGreaterThan(0)
    await screen.findByRole('heading', { name: 'Provenance' })

    expect(await axe(container)).toHaveNoViolations()
  })
})
