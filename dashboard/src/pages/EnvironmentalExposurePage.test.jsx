import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EnvironmentalExposurePage from '@/pages/EnvironmentalExposurePage'
import {
  getEnvironmentalExposureIntegrity,
  getEnvironmentalExposureRelationships,
  getEnvironmentalExposureSummary,
  getHazardEvents,
  getHazardIntegrity,
  getHazardSummary,
  getSolidWasteSites,
} from '@/lib/environmental-exposure-api'

vi.mock('@/lib/environmental-exposure-api', async (importOriginal) => ({
  // Keep the real SOLID_WASTE_KINDS so the page and its test cannot drift apart.
  ...(await importOriginal()),
  getEnvironmentalExposureSummary: vi.fn(),
  getEnvironmentalExposureRelationships: vi.fn(),
  getEnvironmentalExposureIntegrity: vi.fn(),
  getHazardSummary: vi.fn(),
  getHazardEvents: vi.fn(),
  getHazardIntegrity: vi.fn(),
  getSolidWasteSites: vi.fn(),
}))

// Shapes and values are rows from the committed registry (data/environmental_entities.jsonl).
const CLOSED_LMOP = {
  entity_id: 'AYL_ENV_0446bea5742dd3bce992c811',
  authority: 'EPA_LMOP',
  authority_id: '1930',
  entity_kind: 'LANDFILL',
  name_raw: 'Cayey Landfill',
  canonical_name: null,
  municipality: 'Cayey',
  review_status: 'accepted',
  valid_from: '1972',
  valid_until: '2017',
}
const OPEN_LMOP = {
  entity_id: 'AYL_ENV_057233c904ce24701ea2ba7d',
  authority: 'EPA_LMOP',
  authority_id: '2340',
  entity_kind: 'LANDFILL',
  name_raw: 'Anasco Landfill',
  canonical_name: null,
  municipality: 'Anasco',
  review_status: 'accepted',
  valid_from: '1967',
  valid_until: null,
}
const ECHO_FACILITY = {
  entity_id: 'AYL_ENV_332d50c5ff140605e43d687e',
  authority: 'EPA_ECHO_FRS',
  authority_id: '110054266637',
  entity_kind: 'SOLID_WASTE_FACILITY',
  name_raw: 'COMMERCIAL INCINERATION',
  canonical_name: null,
  municipality: 'Carolina',
  review_status: 'needs_review',
  valid_from: null,
  valid_until: null,
}
const SITES = [ECHO_FACILITY, CLOSED_LMOP, OPEN_LMOP]

const summary = (entityKind) => ({
  scope: { statement: 'Temporal environmental graph.' },
  counts: { entities: 3, observations: 0, geometries: 3, relationships: 0, events: 1 },
  entity_kind: entityKind,
  causal_state: {},
  predicate: {},
  pfas: null,
})
const INTEGRITY = { structural_integrity_state: 'PASS', error_count: 0, corpus_certification_state: 'OPEN' }

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <EnvironmentalExposurePage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getEnvironmentalExposureSummary.mockResolvedValue(summary({ LANDFILL: 2, SOLID_WASTE_FACILITY: 1 }))
  getEnvironmentalExposureRelationships.mockResolvedValue({ total: 0, items: [] })
  getEnvironmentalExposureIntegrity.mockResolvedValue(INTEGRITY)
  getHazardSummary.mockResolvedValue(null)
  getHazardEvents.mockResolvedValue({ total: 0, items: [] })
  getHazardIntegrity.mockResolvedValue(null)
  getSolidWasteSites.mockResolvedValue({ total: 3, items: SITES })
})

const section = () => screen.findByRole('region', { name: 'Solid-waste site registry' })

describe('EnvironmentalExposurePage solid-waste registry', () => {
  it('lists every site with its source record, kind and review state', async () => {
    renderPage()
    const region = await section()
    await within(region).findByText('Cayey Landfill')
    const rows = within(region).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(3)
    const cayey = within(region).getByText('Cayey Landfill').closest('tr')
    expect(cayey).toHaveTextContent('EPA_LMOP · 1930')
    expect(cayey).toHaveTextContent('landfill')
    expect(cayey).toHaveTextContent('1972')
    expect(cayey).toHaveTextContent('accepted')
    expect(within(region).getByText(/3 records · 1 need review/)).toBeInTheDocument()
  })

  it('never calls a site open: a missing closure is "none recorded" or "not stated"', async () => {
    renderPage()
    const region = await section()
    await within(region).findByText('Anasco Landfill')
    expect(within(region).getByText('Anasco Landfill').closest('tr')).toHaveTextContent('No closure recorded')
    expect(within(region).getByText('Cayey Landfill').closest('tr')).toHaveTextContent('Closed 2017')
    // An ECHO row carries no status at all, so no closure wording may be inferred for it.
    expect(within(region).getByText('COMMERCIAL INCINERATION').closest('tr')).toHaveTextContent('Not stated by source')
    expect(within(region).queryByText(/^open$/i, { selector: 'td' })).toBeNull()
  })

  it('lists accepted records before records that need review', async () => {
    renderPage()
    const region = await section()
    await within(region).findByText('Cayey Landfill')
    const names = within(region).getAllByRole('row').slice(1).map((row) => row.cells[0].textContent)
    expect(names).toEqual(['Anasco Landfill', 'Cayey Landfill', 'COMMERCIAL INCINERATION'])
  })

  it('states that the registry is bounded and not a finding about contamination', async () => {
    renderPage()
    const region = await section()
    expect(within(region).getByText(/not a complete inventory/i)).toBeInTheDocument()
    expect(within(region).getByText(/nothing about contamination or exposure/i)).toBeInTheDocument()
    expect(within(region).getByText('OPEN')).toBeInTheDocument()
  })

  it('refuses to show an empty list as "no sites" when the summary says sites exist', async () => {
    // The client falls back to an empty list on any failed request.
    getSolidWasteSites.mockResolvedValue({ total: 0, items: [] })
    renderPage()
    const region = await section()
    const alert = await within(region).findByRole('alert')
    expect(alert).toHaveTextContent(/does not match the graph summary \(3\)/)
    expect(within(region).queryByText(/No solid-waste site records/)).toBeNull()
  })

  it('treats a truncated list as incomplete', async () => {
    getSolidWasteSites.mockResolvedValue({ total: 3, items: [CLOSED_LMOP] })
    renderPage()
    const region = await section()
    expect(await within(region).findByRole('alert')).toHaveTextContent(/1 received/)
  })

  it('shows the empty state only when the summary also reports no solid-waste entities', async () => {
    getEnvironmentalExposureSummary.mockResolvedValue(summary({ PUBLIC_WATER_SYSTEM: 4 }))
    getSolidWasteSites.mockResolvedValue({ total: 0, items: [] })
    renderPage()
    const region = await section()
    expect(await within(region).findByText(/No solid-waste site records are materialized/)).toBeInTheDocument()
    expect(within(region).queryByRole('alert')).toBeNull()
  })

  it('does not render the registry when the graph API is unavailable', async () => {
    getEnvironmentalExposureSummary.mockResolvedValue(null)
    renderPage()
    // The hazard plane shows its own alert too, so match the exposure message specifically.
    expect(await screen.findByText(/environmental exposure API is unavailable/i)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Solid-waste site registry' })).toBeNull()
    expect(getSolidWasteSites).not.toHaveBeenCalled()
  })

  it('has no accessibility violations', async () => {
    const { container } = renderPage()
    const region = await section()
    await within(region).findByText('Cayey Landfill')
    expect(await axe(container)).toHaveNoViolations()
  })
})
