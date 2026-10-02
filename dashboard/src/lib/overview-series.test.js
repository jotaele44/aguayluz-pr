import { describe, expect, it } from 'vitest'
import { reservoirStorageSeries } from './overview-series'

const row = (overrides = {}) => ({ site_no: '001', metric: 'reservoir_storage_pct', unit: '%', value: 40, observed_date: '2026-09-01', ...overrides })

describe('overview reservoir series', () => {
  it('keeps exact site IDs and orders one metric without converting units or nulls', () => {
    const rows = [row({ observed_date: '2026-09-03', value: 0 }), row(), row({ site_no: '1' }), row({ unit: 'ft' }), row({ value: null }), row({ metric: 'reservoir_elevation' }), row({ value: 101 }), row({ observed_date: 'invalid' })]
    const result = reservoirStorageSeries(rows, '001')
    expect(result.points).toEqual([{ t: '2026-09-01', v: 40 }, { t: '2026-09-03', v: 0 }])
    expect(result.excluded).toBe(5)
    expect(rows[0].value).toBe(0)
  })

  it('excludes every tied timestamp instead of selecting an arbitrary observation', () => {
    expect(reservoirStorageSeries([row(), row({ value: 50 })], '001')).toEqual({ points: [], excluded: 2 })
  })

  it('rejects calendar rollover and ambiguous or timezone-free timestamps', () => {
    const rows = ['2026-02-30', '09/01/2026', '2026-09-01T12:00:00', '2026-09-01T12:00:00Z'].map((observed_date) => row({ observed_date }))
    expect(reservoirStorageSeries(rows, '001')).toEqual({ points: [{ t: '2026-09-01T12:00:00Z', v: 40 }], excluded: 3 })
  })

  it('does not plot unbound sites and retains only the newest 30 valid points', () => {
    expect(reservoirStorageSeries([null], '001').points).toEqual([])
    expect(reservoirStorageSeries([row({ site_no: undefined })], undefined).points).toEqual([])
    const rows = Array.from({ length: 40 }, (_, i) => row({ observed_date: new Date(Date.UTC(2026, 0, i + 1)).toISOString(), value: i }))
    const result = reservoirStorageSeries(rows.reverse(), '001')
    expect(result.points).toHaveLength(30)
    expect(result.points[0].v).toBe(10)
    expect(result.points[29].v).toBe(39)
    expect(result.excluded).toBe(0)
  })
})
