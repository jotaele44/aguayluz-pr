import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AquiferSeriesChart from '@/components/AquiferSeriesChart'
import * as client from '@/lib/hydro-inventory-api'

vi.mock('@/lib/hydro-inventory-api', () => ({ getAquiferSeries: vi.fn(), getStreamTiles: vi.fn() }))

const BASE = {
  aquifer: 'AQ:USGS_AQFR:110SCPL', limits: 'Median of each well’s departure from its own normal for that calendar month. It is not a water-table elevation and not a storage or volume estimate.',
  members: [{ site_no: 'A', binding: 'USGS_AQUIFER_CODE' }, { site_no: 'B', binding: 'USGS_AQUIFER_CODE' }, { site_no: 'C', binding: 'USGS_AQUIFER_CODE' }],
  contributing_wells: ['A', 'B', 'C'], provisional_points: [], excluded_wells: { coded_to_another_aquifer: 4 },
}

function renderChart(props = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={qc}><AquiferSeriesChart aquifer="AQ:USGS_AQFR:110SCPL" aquiferName="South Coastal Plain Alluvial Aquifer" includePolygon={false} {...props} /></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  // recharts' ResponsiveContainer measures its parent; jsdom has no ResizeObserver.
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
})

describe('AquiferSeriesChart', () => {
  it('states the limits and summarises membership and the latest month', async () => {
    client.getAquiferSeries.mockResolvedValue({ ...BASE, readings_present: true, points_with_value: 1,
      points: [{ month: '2026-03', n: 3, wells: ['A', 'B', 'C'], median_ft: 1.7, membership_changed: false }] })
    renderChart()
    expect(await screen.findByText(/latest 2026-03: \+1.7 ft \(n=3\)/)).toBeInTheDocument()
    expect(screen.getByText(/not a water-table elevation/)).toBeInTheDocument()
  })

  it('says when the server has no readings instead of drawing an empty line', async () => {
    client.getAquiferSeries.mockResolvedValue({ ...BASE, readings_present: false, points: [], points_with_value: 0, contributing_wells: [] })
    renderChart()
    expect(await screen.findByText(/This server holds no reading files/)).toBeInTheDocument()
  })

  it('reports wells left out because USGS assigns them to another aquifer', async () => {
    client.getAquiferSeries.mockResolvedValue({ ...BASE, readings_present: true, points: [], points_with_value: 0 })
    renderChart({ includePolygon: true })
    expect(await screen.findByText(/4 wells inside the outline left out because USGS assigns them to another aquifer/)).toBeInTheDocument()
    expect(screen.getByText(/Not enough wells with a five-year record/)).toBeInTheDocument()
  })
})
