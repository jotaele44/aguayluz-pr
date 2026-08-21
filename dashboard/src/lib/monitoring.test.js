import { describe, expect, it } from 'vitest'

import {
  MONITORING_SERIES,
  MONITORING_SERIES_BY_KEY,
  filterSeriesReadings,
  requireMonitoringSeries,
  seriesIdentity,
} from './monitoring'

const peakStreamflow = MONITORING_SERIES_BY_KEY.peak_streamflow
const reservoirStreamflow = MONITORING_SERIES_BY_KEY.streamflow

describe('unit normalization', () => {
  it('keeps ft^3/s readings, which is how USGS publishes annual peaks', () => {
    // Regression. The USGS OGC peaks API emits `unit_of_measure: "ft^3/s"` and
    // scripts/ingest_usgs_peaks.py stores it verbatim. Before normalizeUnit handled the
    // caret form, every peak-streamflow row was dropped here even after the backend
    // returned it — an empty chart from a 4,104-row corpus.
    const readings = [
      { site_no: 'P1', metric: 'streamflow', unit: 'ft^3/s', value: 284000 },
    ]
    expect(filterSeriesReadings(readings, peakStreamflow)).toHaveLength(1)
  })

  it('treats every spelling of cubic feet per second as one unit', () => {
    const readings = ['ft^3/s', 'ft3/s', 'ft³/s', 'cfs', 'FT^3/S'].map((unit) => ({
      metric: 'streamflow', unit, value: 1,
    }))
    expect(filterSeriesReadings(readings, peakStreamflow)).toHaveLength(5)
  })

  it('still refuses a genuinely different unit', () => {
    const readings = [{ metric: 'streamflow', unit: 'ft', value: 1 }]
    expect(filterSeriesReadings(readings, peakStreamflow)).toEqual([])
  })

  it('collapses the spellings in seriesIdentity so one series is not split in two', () => {
    const a = seriesIdentity({ site_no: 'P1', metric: 'streamflow', parameter_code: '00060', unit: 'ft^3/s' })
    const b = seriesIdentity({ site_no: 'P1', metric: 'streamflow', parameter_code: '00060', unit: 'ft³/s' })
    expect(a).toBe(b)
  })
})

describe('metric reuse across corpora', () => {
  it('separates the two streamflow series by sourceKind, not by metric', () => {
    expect(peakStreamflow.metric).toBe(reservoirStreamflow.metric)
    expect(peakStreamflow.sourceKind).not.toBe(reservoirStreamflow.sourceKind)
    expect(peakStreamflow.sourceKind).toBe('usgs_peaks')
    expect(reservoirStreamflow.sourceKind).toBe('reservoir')
  })

  it('separates the two groundwater series the same way', () => {
    const discrete = MONITORING_SERIES_BY_KEY.field_groundwater_level
    const daily = MONITORING_SERIES_BY_KEY.groundwater_level
    expect(discrete.metric).toBe(daily.metric)
    expect(discrete.sourceKind).toBe('usgs_field_measurements')
    expect(daily.sourceKind).toBe('groundwater')
  })

  it('gives every series a unique key even where metrics repeat', () => {
    const keys = MONITORING_SERIES.map((s) => s.key)
    expect(new Set(keys).size).toBe(keys.length)
    // parameterCode joins sourceKind/metric as an identity component for series that
    // share both (precipitation_pct_normal's 30d/90d windows) — mirrors
    // config/monitoring_capabilities.json's series_identity, which lists
    // parameter_code alongside metric/unit for the same reason.
    const pairs = MONITORING_SERIES.map((s) => `${s.sourceKind}:${s.metric}:${s.parameterCode ?? ''}`)
    expect(new Set(pairs).size).toBe(pairs.length)
  })
})

describe('parameter-code-scoped series', () => {
  it('separates the two precipitation windows by parameterCode, not just metric', () => {
    const p30 = MONITORING_SERIES_BY_KEY.precipitation_pct_normal_30d
    const p90 = MONITORING_SERIES_BY_KEY.precipitation_pct_normal_90d
    expect(p30.metric).toBe(p90.metric)
    expect(p30.sourceKind).toBe(p90.sourceKind)
    expect(p30.parameterCode).toBe('30d')
    expect(p90.parameterCode).toBe('90d')

    const readings = [
      { site_no: 'S1', metric: 'precipitation_pct_normal', parameter_code: '30d', unit: '%', value: 40 },
      { site_no: 'S1', metric: 'precipitation_pct_normal', parameter_code: '90d', unit: '%', value: 60 },
    ]
    expect(filterSeriesReadings(readings, p30)).toEqual([readings[0]])
    expect(filterSeriesReadings(readings, p90)).toEqual([readings[1]])
  })

  it('does not filter by parameterCode for series that do not declare one', () => {
    const drought = MONITORING_SERIES_BY_KEY.drought_category
    const readings = [
      { site_no: 'M1', metric: 'drought_category', parameter_code: 'D2', unit: 'category', value: 2 },
    ]
    expect(filterSeriesReadings(readings, drought)).toEqual(readings)
  })
})

describe('series metadata', () => {
  it('gives every series a label, unit and provenance note', () => {
    for (const series of MONITORING_SERIES) {
      expect(series.label).toBeTruthy()
      expect(series.unit).toBeTruthy()
      expect(series.note).toBeTruthy()
    }
  })

  it('says in the note that the historical series are not live feeds', () => {
    // AGENTS.md requires the GUI to expose provenance; for a 1899-> baseline the most
    // important provenance fact is that it is not current operational status.
    expect(MONITORING_SERIES_BY_KEY.peak_streamflow.note).toMatch(/not a live feed/i)
    expect(MONITORING_SERIES_BY_KEY.peak_gage_height.note).toMatch(/historical baseline/i)
    expect(MONITORING_SERIES_BY_KEY.field_groundwater_level.note).toMatch(/Daily Values feed cannot see/i)
  })

  it('rejects an unknown series key rather than rendering nothing', () => {
    expect(() => requireMonitoringSeries('nope')).toThrow(/Unsupported monitoring series/)
  })
})
