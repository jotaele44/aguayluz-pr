export const WATER_LAYER_STATES = ['AVAILABLE', 'PARTIAL', 'PLANNED', 'BLOCKED']

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

export const WATER_MONITORING_LAYERS = [
  { key: 'rivers', label: 'Rivers', state: 'AVAILABLE', series: ['streamflow', 'gage_height'], note: 'USGS streamflow and gage-height observations.' },
  { key: 'reservoirs', label: 'Reservoirs', state: 'AVAILABLE', series: ['reservoir_elevation', 'reservoir_storage_pct'], note: 'Reservoir elevation and storage remain separate metric identities.' },
  { key: 'rainfall', label: 'Rainfall', state: 'AVAILABLE', series: ['precipitation_pct_normal_30d', 'precipitation_pct_normal_90d'], note: 'Current station-derived rainfall context; spatial raster coverage is a separate adapter.' },
  { key: 'groundwater', label: 'Groundwater', state: 'AVAILABLE', series: ['groundwater_level', 'field_groundwater_level'], note: 'Continuous and discrete groundwater observations remain distinct.' },
  { key: 'coastal', label: 'Ocean / coastal', state: 'AVAILABLE', series: ['coastal_water_level'], note: 'NOAA coastal water-level observations.' },
  { key: 'watersheds', label: 'Watersheds & catchments', state: 'PARTIAL', series: [], note: 'Authoritative watershed geometry exists; monitoring-station topology binding is not yet complete.' },
  { key: 'extraction', label: 'Water extraction', state: 'PLANNED', series: [], note: 'Permit/franchise identity must be independently bound before legal-state classification.' },
  { key: 'quality', label: 'Water quality', state: 'PLANNED', series: [], note: 'No metric is exposed until an authoritative source adapter and unit contract pass.' },
]

export function requireExtractionStatus(status) {
  if (!EXTRACTION_STATUSES.includes(status)) throw new Error(`Unsupported extraction status: ${status}`)
  return status
}

export function classifyExtractionRecord(record = {}) {
  if (record.authoritative_enforcement === 'unauthorized') return 'CONFIRMED_UNAUTHORIZED'
  if (record.enforcement_referred === true) return 'ENFORCEMENT_REFERRED'
  if (record.permit_status === 'revoked') return 'PERMIT_REVOKED'
  if (record.permit_status === 'expired') return 'PERMIT_EXPIRED'
  if (record.permit_status === 'pending') return 'PERMIT_PENDING'
  if (record.permit_status === 'active' && record.identity_binding === 'authoritative') return 'AUTHORIZED'
  if (record.search_exhaustive === true && record.permit_match_count === 0) return 'NO_MATCH_FOUND'
  if (record.suspected_unpermitted === true) return 'SUSPECTED_UNPERMITTED'
  return 'UNKNOWN'
}

export function isCertifiableLayer(layer) {
  return layer?.state === 'AVAILABLE'
}
