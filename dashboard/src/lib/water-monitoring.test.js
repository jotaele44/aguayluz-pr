import { describe, expect, it } from 'vitest'
import {
  EXTRACTION_STATUSES,
  WATER_MONITORING_LAYERS,
  assertSingleWaterQualityIdentity,
  assertWaterMonitoringLayerRegistry,
  classifyExtractionRecord,
  filterLayerAssetGeojson,
  filterLayerAssetRows,
  isCertifiableLayer,
  partitionWaterQualityReadings,
  selectWaterQualitySeries,
  waterQualityIdentity,
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

  it('keeps non-PASS layers outside the certifiable set', () => {
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

  it('requires site + parameter_code + unit for a water-quality identity', () => {
    expect(waterQualityIdentity({ metric: 'water_quality', site_no: '1', parameter_code: '00618', unit: 'mg/L' })).toBe('1|00618|mg/L')
    expect(waterQualityIdentity({ metric: 'water_quality', site_no: '1', unit: 'mg/L' })).toBeNull()
    expect(waterQualityIdentity({ metric: 'streamflow', site_no: '1', parameter_code: '00618', unit: 'mg/L' })).toBeNull()
  })

  it('preserves complete water-quality identity groups and rejects incomplete rows', () => {
    const a = { metric: 'water_quality', site_no: '1', parameter_code: '00618', unit: 'mg/L', value: 1 }
    const b = { metric: 'water_quality', site_no: '1', parameter_code: '00618', unit: 'mg/L', value: 2 }
    const c = { metric: 'water_quality', site_no: '1', parameter_code: '01045', unit: 'ug/L', value: 3 }
    const bad = { metric: 'water_quality', site_no: '1', parameter_code: '00618', value: 4 }
    const { groups, rejected } = partitionWaterQualityReadings([a, b, c, bad])
    expect([...groups.keys()]).toEqual(['1|00618|mg/L', '1|01045|ug/L'])
    expect(groups.get('1|00618|mg/L')).toEqual([a, b])
    expect(rejected).toEqual([bad])
  })

  it('never mixes analytes or units in a selected water-quality series', () => {
    const readings = [
      { metric: 'water_quality', site_no: '1', parameter_code: '00618', unit: 'mg/L', value: 1 },
      { metric: 'water_quality', site_no: '1', parameter_code: '00618', unit: 'ug/L', value: 1000 },
      { metric: 'water_quality', site_no: '1', parameter_code: '01045', unit: 'mg/L', value: 2 },
      { metric: 'water_quality', site_no: '2', parameter_code: '00618', unit: 'mg/L', value: 3 },
    ]
    expect(selectWaterQualitySeries(readings, { siteNo: '1', parameterCode: '00618', unit: 'mg/L' })).toEqual([readings[0]])
    expect(selectWaterQualitySeries(readings, { siteNo: '1', parameterCode: '00618' })).toEqual([])
  })

  it('fails a chart certification gate when identities are mixed or incomplete', () => {
    const one = [{ metric: 'water_quality', site_no: '1', parameter_code: '00618', unit: 'mg/L', value: 1 }]
    expect(assertSingleWaterQualityIdentity(one)).toBe(true)
    expect(() => assertSingleWaterQualityIdentity([...one, { ...one[0], parameter_code: '01045' }])).toThrow(/Mixed water-quality identities/)
    expect(() => assertSingleWaterQualityIdentity([{ ...one[0], unit: '' }])).toThrow(/missing site\/parameter\/unit/)
  })

  it('has a valid unique registry and unique extraction state codes', () => {
    expect(assertWaterMonitoringLayerRegistry()).toBe(true)
    expect(new Set(EXTRACTION_STATUSES).size).toBe(EXTRACTION_STATUSES.length)
  })
})
