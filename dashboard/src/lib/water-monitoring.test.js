import { describe, expect, it } from 'vitest'
import {
  EXTRACTION_STATUSES,
  WATER_MONITORING_LAYERS,
  classifyExtractionRecord,
  isCertifiableLayer,
} from './water-monitoring'

describe('water monitoring contracts', () => {
  it('never infers unauthorized extraction from source absence alone', () => {
    expect(classifyExtractionRecord({ permit_match_count: 0 })).toBe('UNKNOWN')
    expect(classifyExtractionRecord({ permit_match_count: 0, search_exhaustive: true })).toBe('NO_MATCH_FOUND')
  })

  it('requires authoritative enforcement for confirmed unauthorized status', () => {
    expect(classifyExtractionRecord({ suspected_unpermitted: true })).toBe('SUSPECTED_UNPERMITTED')
    expect(classifyExtractionRecord({ authoritative_enforcement: 'unauthorized' })).toBe('CONFIRMED_UNAUTHORIZED')
  })

  it('requires authoritative identity binding for authorized status', () => {
    expect(classifyExtractionRecord({ permit_status: 'active' })).toBe('UNKNOWN')
    expect(classifyExtractionRecord({ permit_status: 'active', identity_binding: 'authoritative' })).toBe('AUTHORIZED')
  })

  it('keeps planned and partial layers outside the certifiable set', () => {
    const certifiable = WATER_MONITORING_LAYERS.filter(isCertifiableLayer).map((layer) => layer.key)
    expect(certifiable).toEqual(['rivers', 'reservoirs', 'rainfall', 'groundwater', 'coastal'])
  })

  it('has unique extraction state codes', () => {
    expect(new Set(EXTRACTION_STATUSES).size).toBe(EXTRACTION_STATUSES.length)
  })
})
