// Canonical frontend monitoring taxonomy.
//
// The backend currently stores reservoir elevation, storage percentage,
// streamflow, and gage height in one reservoir_levels.jsonl corpus.  Every
// user-visible series must therefore declare both its source kind and exact
// metric.  Never chart or calculate statistics across metric/unit boundaries.
export const MONITORING_SERIES = [
  {
    key: 'reservoir_elevation',
    label: 'Reservoir elevation',
    sourceKind: 'reservoir',
    metric: 'reservoir_elevation',
    unit: 'ft',
    note: 'USGS NWIS daily reservoir/lake elevation. Missing records are not interpolated.',
  },
  {
    key: 'reservoir_storage_pct',
    label: 'Reservoir storage',
    sourceKind: 'reservoir',
    metric: 'reservoir_storage_pct',
    unit: '%',
    note: 'USGS NWIS daily reservoir storage percentage where published by the source.',
  },
  {
    key: 'streamflow',
    label: 'Streamflow',
    sourceKind: 'reservoir',
    metric: 'streamflow',
    unit: 'ft³/s',
    note: 'USGS NWIS daily discharge. Values are isolated from elevation and gage-height records.',
  },
  {
    key: 'gage_height',
    label: 'Gage height',
    sourceKind: 'reservoir',
    metric: 'gage_height',
    unit: 'ft',
    note: 'USGS NWIS daily gage height. This is not an official flood-stage classification.',
  },
  {
    key: 'groundwater_level',
    label: 'Groundwater depth',
    sourceKind: 'groundwater',
    metric: 'groundwater_level',
    unit: 'ft',
    note: 'USGS NWIS depth to groundwater below land surface. Compare each well against itself.',
  },
  {
    key: 'coastal_water_level',
    label: 'Coastal water level',
    sourceKind: 'coastal',
    metric: 'coastal_water_level',
    unit: 'ft',
    note: 'NOAA CO-OPS daily tide-gauge observations used as a coastal high-water signal.',
  },
  {
    key: 'drought_category',
    label: 'Drought category',
    sourceKind: 'drought',
    metric: 'drought_category',
    unit: 'category',
    note: 'U.S. Drought Monitor (USDM) weekly classification, D0 (abnormally dry) through D4 (exceptional drought); -1 means no drought designation. Official NDMC/USDM severity band per municipio, not a derived proxy.',
  },
  {
    key: 'precipitation_pct_normal_30d',
    label: 'Precipitation, 30-day (% of normal)',
    sourceKind: 'precipitation',
    metric: 'precipitation_pct_normal',
    parameterCode: '30d',
    unit: '%',
    note: 'NOAA NCEI rolling 30-day rainfall vs. the 1991-2020 climatological normal for that station. A corroborating signal for the drought classification above, not an official index. Kept separate from the 90-day window below — different accumulation periods are not comparable in one series.',
  },
  {
    key: 'precipitation_pct_normal_90d',
    label: 'Precipitation, 90-day (% of normal)',
    sourceKind: 'precipitation',
    metric: 'precipitation_pct_normal',
    parameterCode: '90d',
    unit: '%',
    note: 'NOAA NCEI rolling 90-day rainfall vs. the 1991-2020 climatological normal for that station. A corroborating signal for the drought classification above, not an official index.',
  },
  {
    key: 'field_groundwater_level',
    label: 'Groundwater depth (discrete)',
    sourceKind: 'usgs_field_measurements',
    metric: 'groundwater_level',
    unit: 'ft',
    note: 'USGS discrete field measurements — hydrographer visits, a few times a year per well. These are the wells the Daily Values feed cannot see, so this series complements rather than duplicates "Groundwater depth". No alert threshold: 62610 (level above datum) runs opposite to 72019 (depth below surface), and there are no per-site baselines.',
  },
  {
    key: 'peak_streamflow',
    label: 'Annual peak streamflow',
    sourceKind: 'usgs_peaks',
    metric: 'streamflow',
    unit: 'ft³/s',
    note: 'USGS annual peak flow: one instantaneous maximum per water year, 1899 onward. A historical baseline for ranking a current reading against the record — not a live feed, and deliberately not an alerting series.',
  },
  {
    key: 'peak_gage_height',
    label: 'Annual peak stage',
    sourceKind: 'usgs_peaks',
    metric: 'gage_height',
    unit: 'ft',
    note: 'USGS annual peak stage. Two rows can share a water year: the stage at peak discharge and the year’s maximum stage, which need not coincide. Historical baseline, not an alerting series.',
  },
]

export const MONITORING_SERIES_BY_KEY = Object.fromEntries(
  MONITORING_SERIES.map((series) => [series.key, series]),
)

export function requireMonitoringSeries(key) {
  const series = MONITORING_SERIES_BY_KEY[key]
  if (!series) throw new Error(`Unsupported monitoring series: ${key}`)
  return series
}

export function filterSeriesReadings(readings, series) {
  return readings.filter((reading) => {
    if (reading.metric !== series.metric) return false
    if (reading.unit && series.unit && normalizeUnit(reading.unit) !== normalizeUnit(series.unit)) return false
    // Some metrics (e.g. precipitation_pct_normal) share one metric/unit across
    // multiple incomparable windows distinguished only by parameter_code — mirrors
    // config/monitoring_capabilities.json's series_identity, which lists
    // parameter_code alongside metric/unit for exactly this reason.
    if (series.parameterCode && reading.parameter_code !== series.parameterCode) return false
    return true
  })
}

function normalizeUnit(unit) {
  // `ft^3/s` is what the USGS OGC peaks API publishes and what
  // scripts/ingest_usgs_peaks.py stores verbatim. Without it every peak-streamflow row is
  // dropped client-side by filterSeriesReadings even after the backend returns them.
  // Order matters: normalize the caret form BEFORE the bare `ft3/s` rule.
  return String(unit)
    .trim()
    .toLowerCase()
    .replace('ft^3/s', 'ft³/s')
    .replace('ft3/s', 'ft³/s')
    .replace('cfs', 'ft³/s')
}

export function seriesIdentity(reading) {
  return [
    reading.site_no ?? 'unknown',
    reading.metric ?? 'unknown',
    reading.parameter_code ?? 'unknown',
    normalizeUnit(reading.unit ?? 'unknown'),
  ].join('|')
}
