import { describe, expect, it } from 'vitest'

import { safeCaveKarstStatus } from '@/lib/cave-karst-api'

describe('safeCaveKarstStatus', () => {
  it('suppresses stale open status', () => {
    const projected = safeCaveKarstStatus({
      current_status: 'open',
      status_quality: 'stale',
      conflict_hold: false,
      freshness: { stale: true },
    })
    expect(projected.current_status).toBe('unknown')
  })

  it('suppresses conflicted open status', () => {
    const projected = safeCaveKarstStatus({
      current_status: 'open',
      status_quality: 'conflicting',
      conflict_hold: true,
      freshness: { stale: false },
    })
    expect(projected.current_status).toBe('unknown')
  })

  it('preserves a current nonconflicted status', () => {
    const asset = {
      current_status: 'closed',
      status_quality: 'verified',
      conflict_hold: false,
      freshness: { stale: false },
    }
    expect(safeCaveKarstStatus(asset)).toEqual(asset)
  })
})
