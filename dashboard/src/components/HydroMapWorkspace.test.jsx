import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const addSource = vi.fn()
const addLayer = vi.fn()
const handlers = {}
vi.mock('maplibre-gl', () => ({
  setWorkerUrl: vi.fn(),
  NavigationControl: vi.fn(),
  Map: vi.fn().mockImplementation(function MapStub() {
    return {
      addControl: vi.fn(), addSource, addLayer, remove: vi.fn(), getSource: vi.fn(() => null),
      getLayer: vi.fn(() => true), setLayoutProperty: vi.fn(), on: (event, fn) => { handlers[event] = fn },
    }
  }),
}))
vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url', () => ({ default: 'worker.js' }))
vi.mock('@/lib/hydro-inventory-api', () => ({
  getStreamTiles: vi.fn().mockResolvedValue({ tiles: ['21010008'] }),
  hydroAquifersUrl: () => '/hydro/aquifers.geojson',
  hydroGeoUrl: (name) => `/hydro/geo/${name}.geojson`,
  hydroPointsUrl: (type) => `/hydro/points.geojson?type=${type}`,
}))

import HydroMapWorkspace, { MAP_LAYERS } from '@/components/HydroMapWorkspace'

describe('HydroMapWorkspace', () => {
  it('adds only source geometry layers and lets each be toggled', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={qc}><HydroMapWorkspace /></QueryClientProvider>)
    handlers['style.load']()
    const sources = addSource.mock.calls.map((c) => c[1].data)
    expect(sources).toEqual(expect.arrayContaining(['/hydro/aquifers.geojson', '/hydro/geo/waterbodies.geojson', '/hydro/points.geojson?type=well']))
    expect(addLayer.mock.calls.map((c) => c[0].id)).toEqual(expect.arrayContaining(['aquifers-fill', 'wells', 'springs']))
    const toggles = screen.getAllByRole('checkbox')
    expect(toggles).toHaveLength(MAP_LAYERS.length)
    fireEvent.click(screen.getByLabelText('Stream reaches and canals'))
    expect(screen.getByLabelText('Stream reaches and canals')).toBeChecked()
    expect(screen.getByText(/never placed/)).toBeInTheDocument()
    // phase 5 layers: dams on by default, wetlands and facility networks opt-in
    expect(screen.getByLabelText('Dams (NID)')).toBeChecked()
    expect(screen.getByLabelText('Wetlands (NWI)')).not.toBeChecked()
    expect(screen.getByLabelText('Pump stations and tanks')).not.toBeChecked()
    expect(screen.getByText(/May 2020 layer/)).toBeInTheDocument()
  })
})
