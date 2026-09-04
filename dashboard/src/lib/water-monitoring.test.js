import { describe, expect, it } from 'vitest'
import {
  EXTRACTION_STATUSES,
  WATER_MONITORING_LAYERS,
  assertWaterMonitoringLayerRegistry,
  classifyExtractionRecord,
  filterLayerAssetGeojson,
  filterLayerAssetRows,
  isCertifiableLayer,
} from './water-monitoring'

describe('water monitoring contracts', () => {
  it('never infers unauthorized extraction from source absence alone', () => {
    expect(classifyExtractionRecord({ permit_match_count: 0 })).toBe('UNKNOWN')
    expect(classifyExtractionRecord({ permit_match_count: 0, search_exhaustive: true })).toBe('NO_MATCH_FOUND')
  })

  it('requires an authoritative enforcement finding with a stable finding id for confirmed unauthorized status', () => {
    expect(classifyExtractionRecord({ suspected_unpermitted: true })).toBe('SUSPECTED_UNPERMITTED')
    expect(classifyExtractionRecord({ authoritative_enforcement: 'unauthorized' })).toBe('UNKNOWN')
    expect(classifyExtractionRecord({ authoritative_enforcement: 'unauthorized', enforcement_finding_id: 'DRNA-ENF-1' })).toBe('CONFIRMED_UNAUTHORIZED')
  })

  it('requires authoritative identity binding and a permit id for authorized status', () => {
    expect(classifyExtractionRecord({ permit_status: 'active' })).toBe('UNKNOWN')
    expect(classifyExtractionRecord({ permit_status: 'active', identity_binding: 'authoritative' })).toBe('UNKNOWN')
    expect(classifyExtractionRecord({ permit_status: 'active', identity_binding: 'authoritative', permit_id: 'P-1' })).toBe('AUTHORIZED')
  })

  it('keeps planned and partial layers outside the certifiable set', () => {
    const certifiable = WATER_MONITORING_LAYERS.filter(isCertifiableLayer).map((layer) => layer.key)
    expect(certifiable).toEqual(['rivers', 'reservoirs', 'rainfall', 'groundwater', 'coastal'])
  })

  it('filters whole asset rows only by verified subtype', () => {
    const rivers = WATER_MONITORING_LAYERS.find((layer) => layer.key === 'rivers')
    const rows = [
      { asset_id: 'a', asset_subtype: 'stream_gage', name: 'A' },
      { asset_id: 'b', asset_subtype: 'reservoir', name: 'B' },
    ]
    expect(filterLayerAssetRows(rows, rivers)).toEqual([rows[0]])
  })

  it('filters whole GeoJSON features without synthesizing geometry', () => {
    const reservoirs = WATER_MONITORING_LAYERS.find((layer) => layer.key === 'reservoirs')
    const keep = { type: 'Feature', geometry: { type: 'Point', coordinates: [-66, 18] }, properties: { asset_id: 'r1', asset_subtype: 'reservoir' } }
    const drop = { type: 'Feature', geometry: { type: 'Point', coordinates: [-66.1, 18.1] }, properties: { asset_id: 'g1', asset_subtype: 'stream_gage' } }
    expect(filterLayerAssetGeojson({ type: 'FeatureCollection', features: [keep, drop] }, reservoirs)).toEqual({ type: 'FeatureCollection', features: [keep] })
  })

  it('fails closed for missing geometry collections and non-mappable layers', () => {
    const watersheds = WATER_MONITORING_LAYERS.find((layer) => layer.key === 'watersheds')
    expect(filterLayerAssetGeojson(null, watersheds)).toEqual({ type: 'FeatureCollection', features: [] })
    expect(filterLayerAssetRows([{ asset_id: 'x', asset_subtype: 'stream_gage' }], watersheds)).toEqual([])
  })

  it('has a valid unique registry and unique extraction state codes', () => {
    expect(assertWaterMonitoringLayerRegistry()).toBe(true)
    expect(new Set(EXTRACTION_STATUSES).size).toBe(EXTRACTION_STATUSES.length)
  })
})
