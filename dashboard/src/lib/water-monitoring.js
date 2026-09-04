export const WATER_LAYER_STATES = ['AVAILABLE', 'PARTIAL', 'PLANNED', 'BLOCKED']
export const READINESS_STATES = ['PASS', 'OPEN', 'BLOCKED', 'NOT_APPLICABLE']

export const EXTRACTION_STATUSES = [
  'AUTHORIZED',
  'PERMIT_PENDING',
  'PERMIT_EXPIRED',
  'PERMIT_REVOKED',
  'NO_MATCH_FOUND',
  'SUSPECTED_UNPERMITTED',
  'ENFORCEMENT_REFERRED',
  'CONFIRMED_UNAUTHORIZED',
  'UNKNOWN',
]

export const MONITORING_ALERT_STATES = ['NORMAL', 'WATCH', 'WARNING', 'CRITICAL', 'UNKNOWN', 'STALE']

// Geometry bindings are explicit source manifestations already materialized in the
// canonical AguaYLuz asset plane.  No name, proximity, count, or category heuristic
// may create an asset↔monitoring identity.
export const WATER_MONITORING_LAYERS = [
  {
    key: 'rivers', label: 'Rivers', state: 'AVAILABLE', seriesStatus: 'PASS', geometryStatus: 'PASS',
    series: ['streamflow', 'gage_height'], assetSubtypes: ['stream_gage'], geometry: 'point',
    note: 'USGS streamflow and gage-height observations; mapped only from materialized stream_gage assets.',
  },
  {
    key: 'reservoirs', label: 'Reservoirs', state: 'AVAILABLE', seriesStatus: 'PASS', geometryStatus: 'PASS',
    series: ['reservoir_elevation', 'reservoir_storage_pct'], assetSubtypes: ['reservoir'], geometry: 'point',
    note: 'Reservoir elevation and storage remain separate metric identities; mapped only from reservoir assets.',
  },
  {
    key: 'rainfall', label: 'Rainfall', state: 'AVAILABLE', seriesStatus: 'PASS', geometryStatus: 'PASS',
    series: ['precipitation_pct_normal_30d', 'precipitation_pct_normal_90d'], assetSubtypes: ['precipitation_gauge'], geometry: 'point',
    note: 'NCEI station rainfall context. 30-day and 90-day windows remain distinct identities; raster coverage is separate.',
  },
  {
    key: 'groundwater', label: 'Groundwater', state: 'AVAILABLE', seriesStatus: 'PASS', geometryStatus: 'PASS',
    series: ['groundwater_level', 'field_groundwater_level'], assetSubtypes: ['groundwater_well'], geometry: 'point',
    note: 'Continuous and discrete groundwater observations remain distinct; mapped from groundwater_well assets.',
  },
  {
    key: 'coastal', label: 'Ocean / coastal', state: 'AVAILABLE', seriesStatus: 'PASS', geometryStatus: 'PASS',
    series: ['coastal_water_level'], assetSubtypes: ['tide_gauge'], geometry: 'point',
    note: 'NOAA CO-OPS coastal water-level observations mapped from tide_gauge assets.',
  },
  {
    key: 'watersheds', label: 'Watersheds & catchments', state: 'PARTIAL', seriesStatus: 'NOT_APPLICABLE', geometryStatus: 'OPEN',
    series: [], assetSubtypes: [], geometry: 'polygon',
    note: 'Authoritative SIGE watershed geometry is known, but the frozen polygon snapshot and station topology ledger must close first.',
  },
  {
    key: 'extraction', label: 'Water extraction', state: 'PLANNED', seriesStatus: 'OPEN', geometryStatus: 'OPEN',
    series: [], assetSubtypes: [], geometry: 'point_or_polygon',
    note: 'DRNA permit/franchise identity and physical-well geometry must be independently bound before legal-state classification.',
  },
  {
    key: 'quality', label: 'Water quality', state: 'PLANNED', seriesStatus: 'OPEN', geometryStatus: 'OPEN',
    series: [], assetSubtypes: [], geometry: 'station',
    note: 'No metric is exposed until an authoritative source adapter, unit contract, station identity, and geometry contract pass.',
  },
]

export function requireExtractionStatus(status) {
  if (!EXTRACTION_STATUSES.includes(status)) throw new Error(`Unsupported extraction status: ${status}`)
  return status
}

export function classifyExtractionRecord(record = {}) {
  // Confirmed illegality is an adjudicative/enforcement state, not the result of
  // a failed search or a spatial/name heuristic. Require an authoritative finding
  // plus a stable finding identifier so the assertion is independently auditable.
  if (record.authoritative_enforcement === 'unauthorized' && record.enforcement_finding_id) {
    return 'CONFIRMED_UNAUTHORIZED'
  }
  if (record.enforcement_referred === true) return 'ENFORCEMENT_REFERRED'
  if (record.permit_status === 'revoked') return 'PERMIT_REVOKED'
  if (record.permit_status === 'expired') return 'PERMIT_EXPIRED'
  if (record.permit_status === 'pending') return 'PERMIT_PENDING'
  if (record.permit_status === 'active' && record.identity_binding === 'authoritative' && record.permit_id) return 'AUTHORIZED'
  if (record.search_exhaustive === true && record.permit_match_count === 0) return 'NO_MATCH_FOUND'
  if (record.suspected_unpermitted === true) return 'SUSPECTED_UNPERMITTED'
  return 'UNKNOWN'
}

export function isCertifiableLayer(layer) {
  return layer?.state === 'AVAILABLE' && layer?.seriesStatus === 'PASS' && layer?.geometryStatus === 'PASS'
}

export function filterLayerAssetRows(rows = [], layer) {
  const allowed = new Set(layer?.assetSubtypes ?? [])
  if (!allowed.size) return []
  return rows.filter((row) => allowed.has(row?.asset_subtype))
}

export function filterLayerAssetGeojson(geojson, layer) {
  const allowed = new Set(layer?.assetSubtypes ?? [])
  const features = Array.isArray(geojson?.features) ? geojson.features : []
  if (!allowed.size) return { type: 'FeatureCollection', features: [] }
  return {
    type: 'FeatureCollection',
    // Whole-feature selection only. Never synthesize a feature by combining fields
    // from multiple rows and never invent geometry for a missing source feature.
    features: features.filter((feature) => allowed.has(feature?.properties?.asset_subtype)),
  }
}

export function assertWaterMonitoringLayerRegistry(layers = WATER_MONITORING_LAYERS) {
  const keys = layers.map((layer) => layer.key)
  if (new Set(keys).size !== keys.length) throw new Error('Duplicate water monitoring layer key')
  for (const layer of layers) {
    if (!WATER_LAYER_STATES.includes(layer.state)) throw new Error(`Unsupported layer state: ${layer.state}`)
    if (!READINESS_STATES.includes(layer.seriesStatus)) throw new Error(`Unsupported series readiness: ${layer.seriesStatus}`)
    if (!READINESS_STATES.includes(layer.geometryStatus)) throw new Error(`Unsupported geometry readiness: ${layer.geometryStatus}`)
    if (isCertifiableLayer(layer) && !layer.assetSubtypes.length) throw new Error(`Certifiable layer lacks geometry binding: ${layer.key}`)
  }
  return true
}
