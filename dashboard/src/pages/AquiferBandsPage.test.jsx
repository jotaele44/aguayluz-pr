import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AquiferBandsPage from '@/pages/AquiferBandsPage'
import { getAquiferBands } from '@/lib/aquifer-api'

vi.mock('@/lib/aquifer-api', () => ({ getAquiferBands: vi.fn() }))

// Shapes mirror server/backend/aquifer_api.py. Depths are the real 2026-11-08 provisional readings
// (Aguirre HW 5B 29.76 ft, Constancia 3 9.08 ft) against the bands the USGS page publishes.
// Rasa D is CONSTRUCTED to have no local reading.
const CLASSES = [
  { id: 'above_optimum', label: 'Shallower than Optimum (no legend entry at source)' },
  { id: 'optimum', label: 'Optimum' },
  { id: 'observation', label: 'Observation' },
  { id: 'operational_adjustment', label: 'Operational Adjustment' },
  { id: 'critical', label: 'Critical' },
]

const bands = (edges) => ['above_optimum', 'optimum', 'observation', 'operational_adjustment', 'critical']
  .map((cls, i) => ({ class: cls, shallow_ft: edges[i], deep_ft: edges[i + 1] }))

const well = (overrides) => ({
  revision: 1,
  first_observed_utc: '2026-11-08T16:04:23Z',
  source_byte_sha256: '0d47a55e24a14948c5799f03d8ebe364ea07163d114abbe1bb414f787af015f6',
  ladder_discrepancies: [],
  reference_url: 'https://groundwaterwatch.usgs.gov/AWLSites.asp?S=0&ncd=',
  reading: null,
  class: null,
  class_label: null,
  margin_to_critical_ft: null,
  ...overrides,
})

const AGUIRRE = well({
  site_no: '175947066130601',
  asset_id: 'USGSGW_175947066130601',
  name: 'PIEZOMETER AGUIRRE HW 5B, SALINAS',
  municipality: 'Salinas',
  bands: bands([0, 12.25, 16.54, 21.42, 23.43, 35]),
  axis_max_ft: 35,
  critical_onset_ft: 23.43,
  reference_url: 'https://groundwaterwatch.usgs.gov/AWLSites.asp?S=175947066130601&ncd=',
  ladder_discrepancies: ['observation: chart range ends 21.42 ft, label ladder 21.43 ft'],
  reading: { value_ft: 29.76, observed_date: '2026-11-08', provisional: true, stale: false },
  class: 'critical',
  class_label: 'Critical',
  margin_to_critical_ft: -6.33,
})

const CONSTANCIA = well({
  site_no: '175934066364800',
  asset_id: 'USGSGW_175934066364800',
  name: 'CONSTANCIA 3 WELL, PONCE',
  municipality: 'Ponce',
  bands: bands([0, 8.6, 10.49, 12, 13.65, 15]),
  axis_max_ft: 15,
  critical_onset_ft: 13.65,
  reading: { value_ft: 9.08, observed_date: '2026-11-08', provisional: true, stale: false },
  class: 'optimum',
  class_label: 'Optimum',
  margin_to_critical_ft: 4.57,
})

const RASA_D = well({
  site_no: '175910066155500',
  asset_id: 'USGSGW_175910066155500',
  name: 'PIEZOMETER RASA D, SALINAS',
  municipality: 'Salinas',
  bands: bands([0, 31.6, 38.2, 45.6, 51.55, 60]),
  axis_max_ft: 60,
  critical_onset_ft: 51.55,
})

const SOURCE = {
  source_id: 'prdner_aquifer_bands',
  url: 'https://pr.water.usgs.gov/drought/hydro_conditions_selected_wells.html',
  freshness: { state: 'FRESH', age_seconds: 7200, max_age_seconds: 1209600 },
  receipt: {
    last_status: 'PASS',
    last_attempt_utc: '2026-11-08T16:04:23Z',
    last_error: null,
    last_success_utc: '2026-11-08T16:04:23Z',
    last_success: {
      byte_sha256: '0d47a55e24a14948c5799f03d8ebe364ea07163d114abbe1bb414f787af015f6',
      arithmetic: { source: 5, retained: 5, excluded: 0, unresolved: 0, accounted: 5, delta: 0, state: 'PASS' },
    },
  },
}

const DATA = {
  scope: {
    statement: 'Condition bands that a USGS page attributes to PRDNER. A class is an observed condition, not an alert.',
    completeness_claimed: false,
    evidence_tier: 'T2',
    authority_claim: 'PRDNER, as attributed by the USGS page; not independently verified',
    effective_date: null,
    alerting: 'display_only',
    alerting_reason: 'Display only: the monitoring lifecycle ignores provisional readings by policy.',
  },
  generated_at: '2026-11-08T17:00:00Z',
  source: SOURCE,
  classes: CLASSES,
  counts: { wells: 3, with_reading: 2, provisional_readings: 2, stale_readings: 0, critical: 1 },
  items: [CONSTANCIA, AGUIRRE, RASA_D],
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AquiferBandsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const row = (site) => within(screen.getByTestId(`aquifer-well-${site}`))

beforeEach(() => {
  vi.clearAllMocks()
  getAquiferBands.mockResolvedValue(DATA)
})

describe('AquiferBandsPage', () => {
  it('shows each well with its depth, condition, margin and provisional flag', async () => {
    renderPage()
    await screen.findByRole('table', { name: 'Aquifer observation wells' })

    const aguirre = row('175947066130601')
    expect(aguirre.getByText('Critical')).toBeInTheDocument()
    expect(aguirre.getByText('29.76 ft')).toBeInTheDocument()
    expect(aguirre.getByText('6.33 ft past Critical onset')).toBeInTheDocument()
    expect(aguirre.getByText('Provisional')).toBeInTheDocument()
    expect(aguirre.getByText('Critical from 23.43 ft')).toBeInTheDocument()

    const constancia = row('175934066364800')
    expect(constancia.getByText('Optimum')).toBeInTheDocument()
    expect(constancia.getByText('4.57 ft before Critical')).toBeInTheDocument()
  })

  it('claims no condition for a well that has no reading, and still shows its bands', async () => {
    renderPage()
    await screen.findByRole('table', { name: 'Aquifer observation wells' })
    const rasa = row('175910066155500')
    expect(rasa.getByText('no reading')).toBeInTheDocument()
    expect(rasa.getByText(/No current reading, so no condition is claimed/)).toBeInTheDocument()
    expect(rasa.getByText('Critical: 51.55 – 60 ft')).toBeInTheDocument()
  })

  it('states what the numbers are and why nothing alerts', async () => {
    renderPage()
    // The note is on screen from the first render, with fallback text that already says it is not
    // an alert; the data-driven text (including why nothing alerts) arrives with the response.
    const note = screen.getByRole('note', { name: 'Aquifer bands scope' })
    expect(note).toHaveTextContent('not an alert')
    await screen.findByRole('table', { name: 'Aquifer observation wells' })
    expect(note).toHaveTextContent('Display only: the monitoring lifecycle ignores provisional readings')
  })

  it('counts wells, readings, Critical and provisional', async () => {
    renderPage()
    await screen.findByRole('table', { name: 'Aquifer observation wells' })
    const tile = (label) => screen.getByText(label).closest('div').parentElement
    expect(tile('Wells')).toHaveTextContent('3')
    expect(tile('With a reading')).toHaveTextContent('2')
    expect(tile('In Critical')).toHaveTextContent('1')
    expect(tile('Provisional readings')).toHaveTextContent('2')
  })

  it('describes every band bar in text and places the depth marker on the axis', async () => {
    renderPage()
    await screen.findByRole('table', { name: 'Aquifer observation wells' })
    const bar = screen.getByRole('img', { name: /PIEZOMETER AGUIRRE HW 5B/ })
    expect(bar).toHaveAccessibleName(/Critical 23.43 to 35/)
    expect(bar).toHaveAccessibleName(/Latest depth 29.76 feet/)
    expect(bar.querySelector('div.absolute').style.left).toBe(`${(29.76 / 35) * 100}%`)
    expect(screen.getByRole('img', { name: /RASA D/ })).toHaveAccessibleName(/No current reading/)
    expect(screen.getByRole('img', { name: /RASA D/ }).querySelector('div.absolute')).toBeNull()
  })

  it('clamps the marker for a depth beyond the chart axis, which is still Critical', async () => {
    getAquiferBands.mockResolvedValue({
      ...DATA,
      items: [{
        ...RASA_D,
        reading: { value_ft: 61, observed_date: '2026-11-08', provisional: true, stale: false },
        class: 'critical', class_label: 'Critical', margin_to_critical_ft: -9.45,
      }],
    })
    renderPage()
    await screen.findByRole('table', { name: 'Aquifer observation wells' })
    expect(screen.getByRole('img', { name: /RASA D/ }).querySelector('div.absolute').style.left).toBe('99%')
    expect(row('175910066155500').getByText('9.45 ft past Critical onset')).toBeInTheDocument()
  })

  it('flags a stale reading but still classifies it', async () => {
    getAquiferBands.mockResolvedValue({
      ...DATA,
      items: [{ ...AGUIRRE, reading: { ...AGUIRRE.reading, observed_date: '2026-11-03', stale: true } }],
    })
    renderPage()
    await screen.findByRole('table', { name: 'Aquifer observation wells' })
    const aguirre = row('175947066130601')
    expect(aguirre.getByText('2026-11-03 · stale')).toBeInTheDocument()
    expect(aguirre.getByText('Critical')).toBeInTheDocument()
  })

  it('shows source freshness, the fetched-bytes hash, wells accounted and in-source differences', async () => {
    renderPage()
    const source = within(await screen.findByTestId('aquifer-source'))
    expect(source.getByText('FRESH')).toBeInTheDocument()
    expect(source.getByText(SOURCE.receipt.last_success.byte_sha256)).toBeInTheDocument()
    expect(source.getByText(/5 source = 5 retained \+ 0 excluded \+ 0 unresolved \(PASS\)/)).toBeInTheDocument()
    expect(source.getByText(/effective date not published by the source/)).toBeInTheDocument()
    expect(source.getByRole('link', { name: SOURCE.url })).toHaveAttribute('href', SOURCE.url)
    expect(source.getByText(/label ladder 21.43 ft/)).toBeInTheDocument()
    expect(source.getByText(/does not fetch or verify them/)).toBeInTheDocument()
    expect(source.getByText(/differs on every fetch of identical content/)).toBeInTheDocument()
    expect(source.getByRole('link', { name: 'PIEZOMETER AGUIRRE HW 5B, SALINAS' })).toHaveAttribute(
      'href', 'https://groundwaterwatch.usgs.gov/AWLSites.asp?S=175947066130601&ncd=',
    )
  })

  it('surfaces a failed latest attempt and keeps showing the last verified bands', async () => {
    getAquiferBands.mockResolvedValue({
      ...DATA,
      source: {
        ...SOURCE,
        freshness: { state: 'FAILED', age_seconds: 7200, max_age_seconds: 1209600 },
        receipt: { ...SOURCE.receipt, last_status: 'FAIL', last_error: 'the page no longer parses' },
      },
    })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('the page no longer parses')
    expect(screen.getByRole('alert')).toHaveTextContent('last ones verified')
    expect(screen.getByText('FAILED')).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Aquifer observation wells' })).toBeInTheDocument()
  })

  it('warns when the source page has not been read within its limit', async () => {
    getAquiferBands.mockResolvedValue({
      ...DATA,
      source: { ...SOURCE, freshness: { state: 'STALE', age_seconds: 20 * 86400, max_age_seconds: 1209600 } },
    })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('has not been read successfully within 14 days')
  })

  it('shows a request failure with a retry instead of an empty table', async () => {
    getAquiferBands.mockRejectedValueOnce(new Error('HTTP 502 from /aquifer/bands'))
    renderPage()
    expect(await screen.findByText(/Aquifer bands unavailable: HTTP 502/)).toBeInTheDocument()
    expect(screen.queryByText(/No aquifer bands registered yet/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry aquifer bands' }))
    expect(await screen.findByRole('table', { name: 'Aquifer observation wells' })).toBeInTheDocument()
    expect(getAquiferBands).toHaveBeenCalledTimes(2)
  })

  it('explains an empty registry without inventing wells', async () => {
    getAquiferBands.mockResolvedValue({
      ...DATA,
      counts: { wells: 0, with_reading: 0, provisional_readings: 0, stale_readings: 0, critical: 0 },
      source: { ...SOURCE, freshness: { state: 'NEVER', age_seconds: null, max_age_seconds: 1209600 }, receipt: null },
      items: [],
    })
    renderPage()
    expect(await screen.findByText(/No aquifer bands registered yet/)).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Aquifer observation wells' })).toBeNull()
    expect(screen.queryByTestId('aquifer-source')).toBeNull()
  })

  it('says why there are no bands when the page has never parsed', async () => {
    getAquiferBands.mockResolvedValue({
      ...DATA,
      items: [],
      source: {
        ...SOURCE,
        freshness: { state: 'FAILED', age_seconds: null, max_age_seconds: 1209600 },
        receipt: { last_status: 'FAIL', last_attempt_utc: '2026-11-08T16:04:23Z', last_error: 'the page no longer parses', last_success_utc: null, last_success: null },
      },
    })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('the page no longer parses')
    expect(screen.getByText(/No aquifer bands registered yet/)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderPage()
    await screen.findByRole('table', { name: 'Aquifer observation wells' })
    await screen.findByTestId('aquifer-source')
    expect(await axe(container)).toHaveNoViolations()
  })
})
