// Display-only NWS map overlays, loaded by the browser straight from NOAA/NWS CloudGIS
// (mapservices.weather.noaa.gov — the live successor of the retired idpgis.ncep.noaa.gov
// services listed on weather.gov/gis/IDP-GISRestMetadata). Nothing here is ingested,
// stored or validated by AguaYLuz: these are client-only context layers. The warnings
// AguaYLuz does ingest arrive through scripts/ingest_nws_alerts.py.
//
// Each overlay is an ArcGIS MapServer `export` rendered as 256 px raster tiles; MapLibre
// substitutes {bbox-epsg-3857} per tile. Both services were checked to cover Puerto Rico.

export const CLOUDGIS_HOST = 'https://mapservices.weather.noaa.gov'

// Radar updates every few minutes upstream; re-request tiles on this cadence while shown.
export const OVERLAY_REFRESH_MS = 5 * 60_000

const exportTiles = (service, extra = '') =>
  `${CLOUDGIS_HOST}/${service}/MapServer/export?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857`
  + `&size=256,256&format=png32&transparent=true${extra}&f=image`

export const NWS_CLOUDGIS_OVERLAYS = [
  {
    id: 'nws-radar',
    label: 'NWS radar',
    description: 'MRMS base reflectivity mosaic (includes the San Juan TJUA radar)',
    service: 'eventdriven/rest/services/radar/radar_base_reflectivity',
    tiles: exportTiles('eventdriven/rest/services/radar/radar_base_reflectivity'),
    opacity: 0.7,
  },
  {
    id: 'nws-warnings',
    label: 'NWS warnings',
    description: 'Active watches, warnings and advisories as issued (polygons and zones)',
    service: 'eventdriven/rest/services/WWA/watch_warn_adv',
    tiles: exportTiles('eventdriven/rest/services/WWA/watch_warn_adv', '&layers=show:1'),
    opacity: 0.55,
  },
]

export const OVERLAY_ATTRIBUTION = 'NOAA/NWS CloudGIS'

export const overlaySourceId = (id) => `${id}-source`
export const overlayLayerId = (id) => `${id}-layer`

// Tile URL with a time bucket so a re-shown overlay is not served from MapLibre's tile
// cache long after the upstream image changed.
export function overlayTileUrl(overlay, now = Date.now()) {
  const bucket = Math.floor(now / OVERLAY_REFRESH_MS)
  return `${overlay.tiles}&_t=${bucket}`
}

// Which overlay (if any) a MapLibre `error` event belongs to.
export function overlayForError(event) {
  const sourceId = event?.sourceId ?? event?.source?.id
  return NWS_CLOUDGIS_OVERLAYS.find((o) => overlaySourceId(o.id) === sourceId)?.id ?? null
}
