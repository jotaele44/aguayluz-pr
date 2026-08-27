import { describe, expect, it, vi } from 'vitest'

vi.mock('maplibre-gl', () => ({ default: {} }))

import { eventFeatureCollection } from './AssetMap'

const ASSET_FEATURES = [
  {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [-66.5, 18.3] },
    properties: { asset_id: 'ASSET_1', municipality: 'Ponce' },
  },
  {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [-66.3, 18.1] },
    properties: { asset_id: 'ASSET_2', municipality: 'Ponce' },
  },
]

describe('eventFeatureCollection', () => {
  it('renders direct event lat/lon before asset or municipio approximations', () => {
    const geo = eventFeatureCollection([
      {
        event_id: 'AYL_EVT_20260802_NHC-al052026-adv014',
        event_type: 'service_interruption',
        affected_area: 'Puerto Rico approach corridor',
        evidence_tier: 'T1',
        municipality: null,
        linked_asset_ids: [],
        lat: 17.4,
        lon: -64.2,
      },
    ], [], ASSET_FEATURES)

    expect(geo.features).toHaveLength(1)
    expect(geo.features[0].geometry.coordinates).toEqual([-64.2, 17.4])
    expect(geo.features[0].properties.coordinate_source).toBe('direct_event_coordinates')
    expect(geo.features[0].properties.coord_confidence).toBe('exact')
    expect(geo.features[0].properties.derived).toBe(false)
  })

  it('falls back to linked asset coordinates when direct coordinates are absent', () => {
    const geo = eventFeatureCollection([
      { event_id: 'linked', linked_asset_ids: ['ASSET_1'], municipality: 'Ponce' },
    ], [], ASSET_FEATURES)

    expect(geo.features).toHaveLength(1)
    expect(geo.features[0].geometry.coordinates).toEqual([-66.5, 18.3])
    expect(geo.features[0].properties.coordinate_source).toBe('linked_asset')
    expect(geo.features[0].properties.coord_confidence).toBe('approximate')
    expect(geo.features[0].properties.derived).toBe(true)
  })

  it('falls back to municipio asset averages when no linked asset resolves', () => {
    const geo = eventFeatureCollection([
      { event_id: 'muni', linked_asset_ids: ['missing'], municipality: 'Ponce' },
    ], [], ASSET_FEATURES)

    expect(geo.features).toHaveLength(1)
    expect(geo.features[0].geometry.coordinates[0]).toBeCloseTo(-66.4)
    expect(geo.features[0].geometry.coordinates[1]).toBeCloseTo(18.2)
    expect(geo.features[0].properties.coordinate_source).toBe('municipality_asset_average')
    expect(geo.features[0].properties.coord_confidence).toBe('approximate')
    expect(geo.features[0].properties.derived).toBe(true)
  })

  it('ignores malformed direct coordinates rather than synthesizing a point', () => {
    const geo = eventFeatureCollection([
      { event_id: 'bad', linked_asset_ids: [], municipality: null, lat: 'north', lon: -64.2 },
    ], [], ASSET_FEATURES)

    expect(geo.features).toHaveLength(0)
  })
})
