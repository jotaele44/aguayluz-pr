import { describe, expect, it } from 'vitest'

import {
  bufferPointCandidates,
  measureFeatureCollection,
  nearestPointCandidate,
  pointCandidateSet,
} from './SpatialToolsPanel'

const pointFeature = (id, coordinates) => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates },
  properties: { id },
})

describe('spatial tool analysis', () => {
  it('keeps only finite point candidates and reports every exclusion', () => {
    const result = pointCandidateSet([
      pointFeature('valid', [-66.1, 18.4]),
      pointFeature('invalid', ['west', 18.4]),
      { type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: {} },
      null,
    ])

    expect(result.features.map((feature) => feature.properties.id)).toEqual(['valid'])
    expect(result.excludedCount).toBe(3)
  })

  it('renders every measure vertex in addition to the line', () => {
    const result = measureFeatureCollection([[-66.1, 18.4], [-66.2, 18.3]])

    expect(result.features.map((feature) => feature.geometry.type)).toEqual(['LineString', 'Point', 'Point'])
  })

  it('recomputes buffer membership from the requested radius', () => {
    const candidates = [
      pointFeature('near', [-66.1, 18.4]),
      pointFeature('far', [-66.3, 18.4]),
    ]

    expect(bufferPointCandidates([-66.1, 18.4], 1, candidates).matches).toHaveLength(1)
    expect(bufferPointCandidates([-66.1, 18.4], 25, candidates).matches).toHaveLength(2)
  })

  it('returns an unresolved nearest result when no valid point exists', () => {
    const result = nearestPointCandidate([-66.1, 18.4], [
      { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} },
    ])

    expect(result.nearest).toBeNull()
    expect(result.features).toEqual([])
    expect(result.excludedCount).toBe(1)
  })
})
