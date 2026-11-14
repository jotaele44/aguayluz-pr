import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WaterUsePage from '@/pages/WaterUsePage'
import { getWaterUseEstimates } from '@/lib/water-use-api'

vi.mock('@/lib/water-use-api', () => ({ getWaterUseEstimates: vi.fn() }))

// Shapes mirror server/backend/water_use_api.py. The figures are the published USGS values
// (2020 Table 1, 2015 Tables 4 and 6, OFR 2014-1117 Table 8). The municipality lists are
// CONSTRUCTED subsets of the real 78 rows, with their real values.
const figure = (surface, ground, total, overrides = {}) => {
  const both = surface != null && ground != null
  return {
    surface_water_mgd: surface,
    groundwater_mgd: ground,
    reuse_mgd: null,
    total_mgd: total,
    surface_pct: both ? Math.round((1000 * surface) / (surface + ground)) / 10 : null,
    groundwater_pct: both ? Math.round((1000 * ground) / (surface + ground)) / 10 : null,
    value_status: 'as_published',
    extraction_method: 'xlsx_cell',
    evidence_tier: 'T1',
    notes: [],
    ...overrides,
  }
}
const TRANSCRIBED = { extraction_method: 'manual_transcription', evidence_tier: 'T2' }

const CATEGORIES = [
  { id: 'public_supply', label: 'Public supply' },
  { id: 'domestic_self_supplied', label: 'Domestic self-supplied' },
  { id: 'irrigation', label: 'Irrigation' },
  { id: 'livestock', label: 'Livestock' },
  { id: 'industrial', label: 'Industrial' },
  { id: 'mining', label: 'Mining' },
  { id: 'thermoelectric', label: 'Thermoelectric power (freshwater)' },
  { id: 'total_freshwater', label: 'Total freshwater, all categories' },
]

const YEARS = [
  {
    year: 2010,
    providers: {},
    categories: {
      public_supply: {
        published: figure(590, 87, 677.21, { ...TRANSCRIBED, notes: ['The surface/groundwater split is published only in the body text.'] }),
        restated: figure(null, null, 670, { value_status: 'restated_by_later_release' }),
      },
      irrigation: { published: figure(null, null, 38.16, TRANSCRIBED), restated: figure(null, null, 38) },
      total_freshwater: { published: figure(606.14, 117.61, 723.75, TRANSCRIBED), restated: figure(null, null, 728.23) },
    },
  },
  {
    year: 2015,
    providers: {},
    categories: {
      public_supply: { published: figure(509.78, 66.62, 576.4), restated: null },
      domestic_self_supplied: { published: figure(0, 0.52, 0.52), restated: null },
      irrigation: { published: figure(34.1, 43.48, 77.58), restated: null },
      livestock: { published: figure(1.6, 4.23, 5.83), restated: null },
      industrial: { published: figure(0, 3.67, 3.67), restated: null },
      mining: { published: figure(0.18, 1.84, 2.02), restated: null },
      thermoelectric: { published: figure(2.83, 1.82, 4.65), restated: null },
      total_freshwater: { published: figure(548.49, 122.18, 670.67), restated: null },
    },
  },
  {
    year: 2020,
    providers: {},
    categories: { public_supply: { published: figure(536.64, 65.1, 601.74), restated: null } },
  },
]

const muni = (municipality, surface, ground, total) => ({
  municipality, surface_water_mgd: surface, groundwater_mgd: ground, reuse_mgd: null, total_mgd: total,
})

const SOURCE = {
  source_id: 'usgs_pr_water_use',
  last_status: 'PASS',
  last_success_utc: '2026-11-14T07:00:00Z',
  last_error: null,
  sources: [
    {
      source_key: 'ps_municipio_2020', year: 2020, evidence_tier: 'T1', extraction_method: 'xlsx_cell',
      title: 'Table 1. Estimated public-supply water withdrawals by water source and municipality in Puerto Rico, 2020',
      doi: '10.5066/P9HWON2W', url: 'https://doi.org/10.5066/P9HWON2W',
      sha256: '6d5eaa839908074beb38dc632e765c064b5c940c04d9648470c8055918a28375',
    },
    {
      source_key: 'ofr_2014_1117', year: 2010, evidence_tier: 'T2', extraction_method: 'manual_transcription',
      title: 'Molina-Rivera, W.L., 2014, Estimated water use in Puerto Rico, 2010',
      doi: '10.3133/ofr20141117', url: 'https://doi.org/10.3133/ofr20141117',
      sha256: '39f78c12387c71bfcf800d120c38856f84d7604f8723b1f737a6c3b475f77b8c',
    },
  ],
}

const DATA = {
  scope: {
    statement: 'U.S. Geological Survey estimates of freshwater withdrawals in Puerto Rico for 2010, 2015 and 2020. These are five-yearly compilations, not measurements of current production.',
    completeness_claimed: false,
    unit: 'Mgal/d',
    evidence_tiers: ['T1', 'T2'],
    latest_year: 2020,
    alerting: 'not_applicable',
  },
  generated_at: '2026-11-14T07:05:00Z',
  source: SOURCE,
  categories: CATEGORIES,
  counts: { records: 207, years: 3 },
  years: YEARS,
  municipios: {
    public_supply: {
      2015: [muni('Adjuntas', 1.8, 0.27, 2.07), muni('Salinas', 0, 3.2, 3.2)],
      2020: [muni('Adjuntas', 2.29, 1.09, 3.38), muni('Vega Baja', 0.55, 4.23, 4.78), muni('Vieques', 0, 0, 0)],
    },
    irrigation: {},
  },
  restatements: [
    { year: 2010, category: 'public_supply', published_total_mgd: 677.21, restated_total_mgd: 670, explanation: null },
  ],
  related: { aquifer_bands: '/aquifer-bands' },
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WaterUsePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const yearRow = (year) => within(screen.getByTestId(`water-use-year-${year}`))
const supplyTable = () => screen.findByRole('table', { name: 'Public-supply withdrawals by source' })

beforeEach(() => {
  vi.clearAllMocks()
  getWaterUseEstimates.mockResolvedValue(DATA)
})

describe('WaterUsePage', () => {
  it('shows each year with surface water, groundwater, total and shares', async () => {
    renderPage()
    await supplyTable()
    const y2020 = yearRow(2020)
    expect(y2020.getByText('536.64')).toBeInTheDocument()
    expect(y2020.getByText('65.10')).toBeInTheDocument()
    expect(y2020.getByText('601.74')).toBeInTheDocument()
    expect(y2020.getByText('89.2%')).toBeInTheDocument()
    expect(y2020.getByText('10.8%')).toBeInTheDocument()
    expect(yearRow(2015).getByText('88.4%')).toBeInTheDocument()
  })

  it('summarises the latest year in the tiles', async () => {
    renderPage()
    await supplyTable()
    const tile = (label) => screen.getByText(label).closest('div').parentElement
    expect(tile('Latest year')).toHaveTextContent('2020')
    expect(tile('Public supply (Mgal/d)')).toHaveTextContent('601.74')
    expect(tile('From surface water')).toHaveTextContent('89.2%')
    expect(tile('From groundwater')).toHaveTextContent('10.8%')
  })

  it('marks the 2010 figures as transcribed and shows the later restatement without a reason', async () => {
    renderPage()
    await supplyTable()
    const y2010 = yearRow(2010)
    expect(y2010.getByText('T2 · transcribed from PDF')).toBeInTheDocument()
    expect(y2010.getByText('Restated as 670.00 in a later USGS release')).toBeInTheDocument()
    expect(yearRow(2020).getByText('T1 · data-release table')).toBeInTheDocument()
    const note = screen.getByRole('note', { name: 'Restated figures' })
    expect(note).toHaveTextContent('2010 public supply: 677.21 in the original report, 670.00 in the later release')
    expect(note).toHaveTextContent('The source gives no reason, so none is offered here')
  })

  it('describes every split bar in text', async () => {
    renderPage()
    await supplyTable()
    expect(screen.getByRole('img', { name: /^2020 public supply/ }))
      .toHaveAccessibleName('2020 public supply: 89.2% surface water, 10.8% groundwater')
    expect(screen.getByTestId('split-bar-2020').firstChild.style.width).toBe('89.2%')
  })

  it('says so when a year has no published split, instead of drawing a bar', async () => {
    getWaterUseEstimates.mockResolvedValue({
      ...DATA,
      years: [{ year: 2010, providers: {}, categories: { public_supply: { published: figure(null, null, 677.21, TRANSCRIBED), restated: null } } }],
    })
    renderPage()
    await supplyTable()
    expect(yearRow(2010).getByText('split by source not published')).toBeInTheDocument()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('keeps total freshwater apart from public supply in the category table', async () => {
    renderPage()
    const table = within(await screen.findByRole('table', { name: 'Freshwater withdrawals by category, 2015' }))
    expect(table.getAllByRole('row')).toHaveLength(9)
    const total = within(table.getByRole('row', { name: /Total freshwater, all categories/ }))
    expect(total.getByText('670.67')).toBeInTheDocument()
    expect(total.getByText('18.2%')).toBeInTheDocument()
    expect(screen.getByText(/its split by source is not the\s+public-supply split/)).toBeInTheDocument()
  })

  it('lists municipalities for the newest year, largest groundwater first, and switches year', async () => {
    renderPage()
    const table = await screen.findByRole('table', { name: 'Public-supply withdrawals by municipality, 2020' })
    const names = within(table).getAllByRole('rowheader').map((cell) => cell.textContent)
    expect(names).toEqual(['Vega Baja', 'Adjuntas', 'Vieques'])
    expect(screen.getByRole('button', { name: '2020' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: '2015' }))
    const older = screen.getByRole('table', { name: 'Public-supply withdrawals by municipality, 2015' })
    expect(within(older).getAllByRole('rowheader').map((cell) => cell.textContent)).toEqual(['Salinas', 'Adjuntas'])
  })

  it('states what the numbers are and links to the aquifer bands', async () => {
    renderPage()
    const note = screen.getByRole('note', { name: 'Water use scope' })
    expect(note).toHaveTextContent('not measurements of current production')
    expect(within(note).getByRole('link', { name: 'Aquifer Bands' })).toHaveAttribute('href', '/aquifer-bands')
    await supplyTable()
    expect(note).toHaveTextContent('five-yearly compilations')
  })

  it('shows each source with its DOI, tier and pinned hash', async () => {
    renderPage()
    const source = within(await screen.findByTestId('water-use-source'))
    expect(source.getByText('PASS')).toBeInTheDocument()
    expect(source.getByRole('link', { name: 'doi:10.5066/P9HWON2W' })).toHaveAttribute('href', 'https://doi.org/10.5066/P9HWON2W')
    expect(source.getByText('T2 · transcribed from PDF')).toBeInTheDocument()
    expect(source.getByText(/SHA-256 6d5eaa83/)).toBeInTheDocument()
  })

  it('shows a failed read while keeping the last verified figures', async () => {
    getWaterUseEstimates.mockResolvedValue({
      ...DATA,
      source: { ...SOURCE, last_status: 'FAIL', last_error: 'ps_municipio_2020: SHA-256 differs from the pin' },
    })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('SHA-256 differs from the pin')
    expect(yearRow(2020).getByText('601.74')).toBeInTheDocument()
  })

  it('offers a retry when the request fails', async () => {
    getWaterUseEstimates.mockRejectedValueOnce(new Error('HTTP 502 from /water-use/estimates'))
    renderPage()
    expect(await screen.findByText(/Water-use estimates unavailable: HTTP 502/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry water use' }))
    await supplyTable()
    expect(getWaterUseEstimates).toHaveBeenCalledTimes(2)
  })

  it('explains an empty workspace without inventing figures', async () => {
    getWaterUseEstimates.mockResolvedValue({
      ...DATA,
      counts: { records: 0, years: 0 },
      years: [],
      municipios: { public_supply: {}, irrigation: {} },
      restatements: [],
      source: { ...SOURCE, last_status: null, last_success_utc: null },
    })
    renderPage()
    expect(await screen.findByText(/No water-use estimates loaded yet/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.queryByTestId('water-use-source')).toBeNull()
    expect(screen.getByText('Latest year').closest('div').parentElement).toHaveTextContent('—')
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderPage()
    await supplyTable()
    await screen.findByTestId('water-use-source')
    expect(await axe(container)).toHaveNoViolations()
  })
})
