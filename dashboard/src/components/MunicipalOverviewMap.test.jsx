import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import MunicipalOverviewMap from '@/components/MunicipalOverviewMap'

const square = (x) => ({
  type: 'Polygon',
  coordinates: [[[x, 18], [x + 0.1, 18], [x + 0.1, 18.1], [x, 18.1], [x, 18]]],
})

const geojson = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', properties: { name: 'Adjuntas', geoid: '72001' }, geometry: square(-66.8) },
    { type: 'Feature', properties: { name: 'Aguada', geoid: '72003' }, geometry: square(-67.2) },
  ],
}

const summary = {
  municipality_denominator: 78,
  geometry_feature_count: 78,
  unique_geoid_count: 78,
  items: [
    { geoid: '72001', name: 'Adjuntas', asset_count: 3, active_asset_count: 2, event_count: 5, active_outage_count: 1 },
    { geoid: '72003', name: 'Aguada', asset_count: 1, active_asset_count: 1, event_count: 2, active_outage_count: 0 },
  ],
}

const renderMap = (props = {}) => render(
  <MemoryRouter>
    <MunicipalOverviewMap geojson={geojson} summary={summary} {...props} />
  </MemoryRouter>,
)

describe('MunicipalOverviewMap', () => {
  it('binds interaction to GEOID-backed summary rows', () => {
    const onSelect = vi.fn()
    renderMap({ onSelect })
    fireEvent.click(screen.getByRole('button', { name: 'Adjuntas: Assets 3' }))
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ geoid: '72001', name: 'Adjuntas' }))
  })

  it('supports keyboard selection', () => {
    const onSelect = vi.fn()
    renderMap({ onSelect })
    fireEvent.keyDown(screen.getByRole('button', { name: 'Aguada: Assets 1' }), { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ geoid: '72003' }))
  })

  it('changes municipal metric without inventing a composite score', () => {
    const onMetricChange = vi.fn()
    renderMap({ metric: 'outages', onMetricChange })
    expect(screen.getByRole('group', { name: /colored by active outages/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Events' }))
    expect(onMetricChange).toHaveBeenCalledWith('events')
  })
})
