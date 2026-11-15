import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import HydroInventoryPage from '@/pages/HydroInventoryPage'
import * as client from '@/lib/hydro-inventory-api'

vi.mock('@/lib/hydro-inventory-api', () => ({
  getHydroSummary: vi.fn(),
  getHydroFeatures: vi.fn(),
  getHydroFeature: vi.fn(),
  getHydroConflicts: vi.fn(),
  getHydroCandidates: vi.fn(),
  getAquiferWells: vi.fn(),
}))

// Shapes mirror server/backend/hydro_inventory_api.py; rows are copied from data/hydro/features.jsonl.
const SUMMARY = {
  scope: { statement: 'Every aquifer and well that the enumerated public sources describe for Puerto Rico. Name or distance matches are listed as candidates.', completeness_claimed: false },
  generated_at: '2026-11-15T02:00:00Z',
  phase_scope: { feature_types_enumerated: ['aquifer', 'well'], feature_types_not_enumerated: ['spring', 'stream'] },
  coverage: {
    aquifer: { features_upper: 159, features_lower: 141 },
    well: { features_upper: 7061, features_lower: 7001, unlocated: 1384, located: 5677 },
  },
  source_ledgers: { epa_sdwis_wells: { source: 1384, assigned_to_features: 1384, excluded_by_reason: {}, state: 'PASS' } },
  open_residue: ['PRASA production wells: EPA SDWIS lists them without coordinates'],
  datum: { used: 'EPSG:4139 Puerto Rico 1940', checks: { declared_nad27: { median_north_offset_m: 209.5 }, puerto_rico_1940: { median_m: 25.9 } } },
  monitoring: { readings_present: false, wells_by_state: { READINGS_ABSENT_ON_SERVER: 7061 } },
  conflicts: 16,
  sources: [],
}
const AQUIFERS = { total: 2, items: [
  { feature_id: 'AQ:USGS_AQFR:110SCPL', feature_type: 'aquifer', display_name: 'South Coastal Plain Alluvial Aquifer', sources: ['usgs_aquifer_codes'], member_wells: { AUTHORITATIVE: 145, DERIVED_TOPOLOGICAL: 0 } },
  { feature_id: 'AQ:HA730:115:main:c42', feature_type: 'aquifer', display_name: 'Alluvial-valley aquifer', sources: ['usgs_ha730_aquifers_pr'], island: 'main', municipios: ['Carolina', 'San Juan', 'Toa Baja'], area_km2: 203.201, name_is_source_class_only: true, member_wells: { AUTHORITATIVE: 0, DERIVED_TOPOLOGICAL: 412 } },
] }
const WELLS = { total: 2, offset: 0, limit: 50, items: [
  { feature_id: 'WELL:USGS:175947066130601', feature_type: 'well', display_name: 'PIEZOMETER AGUIRRE HW 5B, SALINAS, PR', sources: ['usgs_monitoring_locations', 'wqp_wells'], aquifer_code: '110SCPL', lat: 17.994133, lon: -66.216, located: true, monitoring: { state: 'READINGS_ABSENT_ON_SERVER', last_observed_date: null } },
  { feature_id: 'WELL:SDWIS:PR0003373:1312', feature_type: 'well', display_name: 'CABO ROJO I', sources: ['epa_sdwis_wells'], located: false, monitoring: { state: 'NO_DATA', last_observed_date: null } },
] }
const CONFLICTS = { total: 1, items: [{
  conflict_id: 'HYC_1', attribute: 'south_coast_aquifer_units', kind: 'classification', resolution: 'UNRESOLVED_SHOWN', feature_ids: [],
  values_by_claim: [{ source_key: 'usgs_ha730_aquifers_pr', value: "one 'South coast aquifer'" }, { source_key: 'drna_pira_2016', value: 'independent valley aquifers' }],
}] }
const CANDIDATES = { total: 1, items: [{
  link_id: 'HYL_1', link_type: 'CANDIDATE_SAME_FEATURE', from: 'WELL:WQP:PREQB_GW-PAJUIL', to: 'WELL:USGS:182556066472400', from_name: 'PAJUIL', to_name: 'PAJUIL 3 WELL, HATILLO, PR', evidence_classes: ['NORMALIZED_NAME', 'PROXIMITY'], identity_tier: 'I4', distance_m: 82.8, adjudication_state: 'CANDIDATE_NOT_IDENTITY',
}] }
const DETAIL = {
  feature: { ...WELLS.items[0], identity_evidence: [] },
  claims: [{ claim_id: 'HCL_a', source_key: 'usgs_monitoring_locations', name_raw: 'PIEZOMETER AGUIRRE HW 5B, SALINAS, PR', evidence_tier: 'T1', extraction_method: 'parsed', source_feature_id: '175947066130601', lat: 17.994133, lon: -66.216, manifestation_sha256: 'a'.repeat(64) },
    { claim_id: 'HCL_b', source_key: 'wqp_wells', name_raw: 'PIEZOMETER AGUIRRE HW 5B, SALINAS, PR', evidence_tier: 'T2', extraction_method: 'parsed', source_feature_id: 'USGS-175947066130601', lat: 17.99413, lon: -66.2160, manifestation_sha256: 'b'.repeat(64) }],
  links: [{ link_id: 'HYL_w', link_type: 'WELL_IN_AQUIFER', from: 'WELL:USGS:175947066130601', to: 'AQ:USGS_AQFR:110SCPL', edge_class: 'AUTHORITATIVE' }],
  member_wells: { authoritative: 0, polygon_only: 0 },
  conflicts: [],
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><HydroInventoryPage /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  client.getHydroSummary.mockResolvedValue(SUMMARY)
  client.getHydroFeatures.mockImplementation((params) => Promise.resolve(params.type === 'aquifer' ? AQUIFERS : WELLS))
  client.getHydroFeature.mockResolvedValue(DETAIL)
  client.getHydroConflicts.mockResolvedValue(CONFLICTS)
  client.getHydroCandidates.mockResolvedValue(CANDIDATES)
})

describe('HydroInventoryPage', () => {
  it('shows coverage as ranges and says when readings are absent from the server', async () => {
    renderPage()
    expect(await screen.findByTestId('tile-aquifers')).toHaveTextContent('141–159')
    expect(screen.getByTestId('tile-wells')).toHaveTextContent('7001–7061')
    expect(screen.getByTestId('tile-unlocated')).toHaveTextContent('1384')
    expect(screen.getByText(/property of this server, not of the wells/)).toBeInTheDocument()
  })

  it('lists aquifers with their coded and in-outline wells and flags unnamed map polygons', async () => {
    renderPage()
    const table = await screen.findByRole('table', { name: 'Aquifers' })
    const coded = within(screen.getByTestId('aquifer-AQ:USGS_AQFR:110SCPL'))
    expect(coded.getByText('145')).toBeInTheDocument()
    expect(within(table).getByText('unnamed in the source; labelled by location')).toBeInTheDocument()
  })

  it('lists wells with their sources, and a well without a published location says so', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Wells' }))
    const table = await screen.findByRole('table', { name: 'Wells' })
    expect(within(table).getByText('USGS + Water Quality Portal')).toBeInTheDocument()
    expect(within(table).getByText('not published by the source')).toBeInTheDocument()
    expect(within(table).getByText('Readings not on this server')).toBeInTheDocument()
  })

  it('opens a feature and shows what each source says about it', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Wells' }))
    fireEvent.click(await screen.findByRole('button', { name: 'PIEZOMETER AGUIRRE HW 5B, SALINAS, PR' }))
    const detail = await screen.findByTestId('feature-detail')
    expect(within(detail).getByText('What each source says (2)')).toBeInTheDocument()
    expect(within(detail).getByText('Water Quality Portal')).toBeInTheDocument()
    expect(client.getHydroFeature).toHaveBeenCalledWith('WELL:USGS:175947066130601')
  })

  it('shows source disagreements unresolved and candidates as unmerged', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Conflicts' }))
    const conflict = await screen.findByTestId('conflict')
    expect(conflict).toHaveTextContent('south coast aquifer units')
    expect(conflict).toHaveTextContent('unresolved, shown')
    fireEvent.click(screen.getByRole('button', { name: 'Candidates' }))
    expect(await screen.findByText(/None is merged: a name and a distance are not identity/)).toBeInTheDocument()
    expect(screen.getByTestId('candidate')).toHaveTextContent('82.8 m')
  })

  it('states the datum decision and what is not enumerated yet', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Sources & coverage' }))
    const panel = await screen.findByTestId('hydro-sources')
    expect(panel).toHaveTextContent('209.5 m north')
    expect(panel).toHaveTextContent('spring, stream')
  })

  it('offers a retry when the inventory cannot be read', async () => {
    client.getHydroSummary.mockRejectedValueOnce(new Error('HTTP 503 from /hydro/inventory/summary'))
    renderPage()
    expect(await screen.findByText(/Inventory unavailable: HTTP 503/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry inventory' }))
    expect(await screen.findByTestId('tile-aquifers')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderPage()
    await screen.findByRole('table', { name: 'Aquifers' })
    expect(await axe(container)).toHaveNoViolations()
  })
})
