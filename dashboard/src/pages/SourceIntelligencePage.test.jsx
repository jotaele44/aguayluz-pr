import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SourceIntelligencePage from '@/pages/SourceIntelligencePage'
import {
  getSourceIntelligenceCoverage,
  getSourceIntelligenceDomains,
  getSourceIntelligenceProducts,
  getSourceIntelligenceRouteGovernance,
  getSourceIntelligenceRoutes,
  getSourceIntelligenceSources,
  getSourceIntelligenceSummary,
} from '@/lib/api'

vi.mock('@/lib/api', () => ({
  getSourceIntelligenceSummary: vi.fn(),
  getSourceIntelligenceDomains: vi.fn(),
  getSourceIntelligenceSources: vi.fn(),
  getSourceIntelligenceCoverage: vi.fn(),
  getSourceIntelligenceProducts: vi.fn(),
  getSourceIntelligenceRoutes: vi.fn(),
  getSourceIntelligenceRouteGovernance: vi.fn(),
}))

const SUMMARY = {
  api_contract_state: 'FROZEN_V1_CERTIFIED',
  scope: 'Bounded V1 source-family denominator.',
  backend_readiness: { score: 100, states: {}, unresolved: [] },
  coverage_matrix_ready: true,
  coverage: { total_source_families: 31 },
  route_governance: {
    governed_source_families: 31,
    total_products: 63,
    verified_product_identity_count: 63,
    payload_product_denominator_exhausted_family_ids: ['EIA_860M', 'EIA_923'],
    open_payload_product_denominator_family_ids: ['EIA_EPM'],
    payload_product_denominator_complete: false,
    route_governance_coverage_complete: true,
  },
  source_universe_certified: false,
  domain_certification_complete: false,
}

const DOMAINS = {
  total: 1,
  items: [{
    domain_id: 'ENERGY_GENERATION',
    label: 'Energy generation',
    scope: 'Generation inventory and plant state.',
    certification_rule: 'Zero material unresolved source-coverage residue.',
  }],
}

const SOURCES = {
  total: 2,
  items: [
    {
      source_family_id: 'EIA_860M',
      label: 'EIA-860M monthly generator inventory',
      authority: 'U.S. EIA',
      identity_namespace: 'EIA_PLANT_GENERATOR',
      monitoring_mode: 'DISCOVER_NEW_RELEASE',
      adapter_id: 'eia860m',
      mutable: true,
      canonical_locator: 'https://www.eia.gov/electricity/data/eia860m/',
      runtime_health: null,
      runtime_health_reason: 'NO_UNIFIED_RUNTIME_RECEIPT',
      requirements: [{
        domain_id: 'ENERGY_GENERATION',
        role: 'PRIMARY_AUTHORITY',
        required: true,
        adapter_required: true,
        state: 'REGISTERED',
      }],
    },
    {
      source_family_id: 'EIA_EPM',
      label: 'EIA Electric Power Monthly',
      authority: 'U.S. EIA',
      identity_namespace: 'EIA_EPM',
      monitoring_mode: 'DISCOVER_NEW_RELEASE',
      adapter_id: null,
      mutable: true,
      canonical_locator: 'https://www.eia.gov/electricity/monthly/',
      runtime_health: null,
      runtime_health_reason: 'NO_UNIFIED_RUNTIME_RECEIPT',
      requirements: [],
    },
  ],
}

const COVERAGE = {
  summary: {},
  items: [{
    domain_id: 'ENERGY_GENERATION',
    source_family_id: 'EIA_860M',
    role: 'PRIMARY_AUTHORITY',
    required: true,
    adapter_required: true,
    state: 'REGISTERED',
  }],
}

const PRODUCTS = {
  total: 1,
  items: [{
    source_family_id: 'EIA_860M',
    product_id: 'EIA_860M_MONTHLY_GENERATOR',
    identity_state: 'VERIFIED',
    payload_state: 'CANONICAL_ROUTE',
  }],
}

const ROUTES = {
  total: 1,
  items: [{
    product_id: 'EIA_860M_MONTHLY_GENERATOR',
    route_id: 'EIA_860M_INDEX',
    role: 'DISCOVERY',
    representation: 'CATALOG',
    priority: 1,
    locator: 'https://www.eia.gov/electricity/data/eia860m/',
  }],
}

const ROUTE_GOVERNANCE = { summary: SUMMARY.route_governance }

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={client}>
      <SourceIntelligencePage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getSourceIntelligenceSummary.mockResolvedValue(SUMMARY)
  getSourceIntelligenceDomains.mockResolvedValue(DOMAINS)
  getSourceIntelligenceSources.mockResolvedValue(SOURCES)
  getSourceIntelligenceCoverage.mockResolvedValue(COVERAGE)
  getSourceIntelligenceProducts.mockResolvedValue(PRODUCTS)
  getSourceIntelligenceRoutes.mockResolvedValue(ROUTES)
  getSourceIntelligenceRouteGovernance.mockResolvedValue(ROUTE_GOVERNANCE)
})

describe('SourceIntelligencePage', () => {
  it('keeps source-universe certification open even when backend readiness is 100', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Source Intelligence' })).toBeInTheDocument()
    expect(await screen.findByText('Backend certified; source universe still open')).toBeInTheDocument()
    expect(screen.getAllByText('FROZEN_V1_CERTIFIED').length).toBeGreaterThan(0)
    expect(screen.getByText(/1 source families still open/i)).toBeInTheDocument()
    expect(screen.getByText('EIA_EPM')).toBeInTheDocument()
    expect(screen.getByText('NO_UNIFIED_RUNTIME_RECEIPT')).toBeInTheDocument()
  })

  it('lets an open denominator family become the selected source without promoting it', async () => {
    renderPage()

    const gap = await screen.findByRole('button', { name: 'EIA_EPM' })
    fireEvent.click(gap)

    expect(await screen.findByText('EIA Electric Power Monthly')).toBeInTheDocument()
    expect(screen.getAllByText('OPEN').length).toBeGreaterThan(0)
    expect(screen.queryByText('Source universe certified')).not.toBeInTheDocument()
  })
})
