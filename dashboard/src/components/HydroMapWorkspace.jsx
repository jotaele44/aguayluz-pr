import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { Map as MapIcon } from 'lucide-react'
import { hydroAquifersUrl, hydroGeoUrl, hydroPointsUrl } from '@/lib/hydro-inventory-api'
import { useStreamTiles } from '@/lib/hydro-inventory-hooks'

maplibregl.setWorkerUrl(maplibreWorkerUrl)

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'
const PR_CENTER = [-66.45, 18.22]

// Dark basemap only; every hydrologic layer comes from committed source geometry served by the
// backend. Nothing is drawn for a feature whose source publishes no location.
const STYLE = {
  version: 8,
  sources: { osm: { type: 'raster', tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors' } },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#020617' } },
    { id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-opacity': 0.45, 'raster-saturation': -0.85, 'raster-brightness-max': 0.55 } },
  ],
}

const AQUIFER_COLOR = ['match', ['get', 'aq_code'], '4191', '#22c55e', '4192', '#15803d', '114', '#f59e0b', '115', '#38bdf8', '908', '#a78bfa', '#334155']
const WELL_STATE_COLOR = ['match', ['get', 'state'], 'MONITORED_NOW', '#22c55e', 'HISTORICAL_ONLY', '#f59e0b', 'NO_DATA', '#64748b', '#94a3b8']

export const MAP_LAYERS = [
  { key: 'aquifers', label: 'Aquifers (HA 730-N)', on: true },
  { key: 'watersheds', label: 'Watersheds (HUC10)', on: false },
  { key: 'waterbodies', label: 'Waterbodies', on: true },
  { key: 'streams', label: 'Stream reaches and canals', on: false },
  { key: 'wetlands', label: 'Wetlands (NWI)', on: false },
  { key: 'wells', label: 'Wells', on: true },
  { key: 'springs', label: 'Springs', on: true },
  { key: 'gauges', label: 'Gauges', on: false },
  { key: 'dams', label: 'Dams (NID)', on: true },
  { key: 'plants', label: 'Treatment plants', on: false },
  { key: 'network', label: 'Pump stations and tanks', on: false },
]
const LAYER_IDS = {
  aquifers: ['aquifers-fill', 'aquifers-line'], watersheds: ['watersheds-line'], waterbodies: ['waterbodies-fill'],
  streams: [], wetlands: [], wells: ['wells'], springs: ['springs'], gauges: ['gauges'], dams: ['dams'],
  plants: ['treatment_plants', 'wastewater_plants'], network: ['pump_stations', 'tanks'],
}
const HIDDEN_AT_START = ['gauges', 'treatment_plants', 'wastewater_plants', 'pump_stations', 'tanks']

export default function HydroMapWorkspace() {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const [visible, setVisible] = useState(() => Object.fromEntries(MAP_LAYERS.map((l) => [l.key, l.on])))
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(null)
  const [layerErrors, setLayerErrors] = useState([])
  const tiles = useStreamTiles()

  useEffect(() => {
    if (OFFLINE || !containerRef.current) return undefined
    let map
    try {
      map = new maplibregl.Map({ container: containerRef.current, style: STYLE, center: PR_CENTER, zoom: 7.6, minZoom: 6.5 })
    } catch (error) {
      setFailed(String(error?.message ?? error))
      return undefined
    }
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    // A layer that fails to load must say so rather than silently not appear.
    map.on('error', (event) => {
      const message = `${event.sourceId ?? 'map'}: ${event.error?.message ?? 'error'}`
      console.error(`HydroMapWorkspace ${message}`)
      setLayerErrors((list) => (list.includes(message) || list.length > 5 ? list : [...list, message]))
    })
    map.on('style.load', () => {
      map.addSource('aquifers', { type: 'geojson', data: hydroAquifersUrl() })
      map.addSource('watersheds', { type: 'geojson', data: hydroGeoUrl('watersheds') })
      map.addSource('waterbodies', { type: 'geojson', data: hydroGeoUrl('waterbodies') })
      map.addSource('wells', { type: 'geojson', data: hydroPointsUrl('well') })
      map.addSource('springs', { type: 'geojson', data: hydroPointsUrl('spring') })
      map.addSource('gauges', { type: 'geojson', data: hydroPointsUrl('gauge') })
      for (const [id, type] of [['dams', 'dam'], ['treatment_plants', 'treatment_plant'], ['wastewater_plants', 'wastewater_plant'], ['pump_stations', 'pump_station'], ['tanks', 'tank']]) {
        map.addSource(id, { type: 'geojson', data: hydroPointsUrl(type) })
      }
      map.addLayer({ id: 'aquifers-fill', type: 'fill', source: 'aquifers', filter: ['==', ['get', 'disposition'], 'RETAINED'], paint: { 'fill-color': AQUIFER_COLOR, 'fill-opacity': 0.28 } })
      map.addLayer({ id: 'aquifers-line', type: 'line', source: 'aquifers', filter: ['==', ['get', 'disposition'], 'RETAINED'], paint: { 'line-color': AQUIFER_COLOR, 'line-width': 0.6 } })
      map.addLayer({ id: 'watersheds-line', type: 'line', source: 'watersheds', filter: ['==', ['get', 'level'], 'huc10'], paint: { 'line-color': '#e2e8f0', 'line-width': 0.8, 'line-dasharray': [2, 2] } })
      map.addLayer({ id: 'waterbodies-fill', type: 'fill', source: 'waterbodies', paint: { 'fill-color': ['match', ['get', 'kind'], 'reservoir', '#2563eb', '#0ea5e9'], 'fill-opacity': 0.7 } })
      map.addLayer({ id: 'wells', type: 'circle', source: 'wells', paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 1.6, 12, 4], 'circle-color': WELL_STATE_COLOR, 'circle-stroke-width': ['case', ['get', 'coded'], 0.8, 0], 'circle-stroke-color': '#f8fafc' } })
      map.addLayer({ id: 'springs', type: 'circle', source: 'springs', paint: { 'circle-radius': 3.2, 'circle-color': '#06b6d4', 'circle-stroke-width': 1, 'circle-stroke-color': '#020617' } })
      map.addLayer({ id: 'gauges', type: 'circle', source: 'gauges', paint: { 'circle-radius': 2.4, 'circle-color': '#e879f9' } })
      map.addLayer({ id: 'tanks', type: 'circle', source: 'tanks', paint: { 'circle-radius': 1.8, 'circle-color': '#a3a3a3' } })
      map.addLayer({ id: 'pump_stations', type: 'circle', source: 'pump_stations', paint: { 'circle-radius': 1.8, 'circle-color': '#fb923c' } })
      map.addLayer({ id: 'treatment_plants', type: 'circle', source: 'treatment_plants', paint: { 'circle-radius': 3.2, 'circle-color': '#facc15', 'circle-stroke-width': 1, 'circle-stroke-color': '#020617' } })
      map.addLayer({ id: 'wastewater_plants', type: 'circle', source: 'wastewater_plants', paint: { 'circle-radius': 3.2, 'circle-color': '#a16207', 'circle-stroke-width': 1, 'circle-stroke-color': '#020617' } })
      map.addLayer({ id: 'dams', type: 'symbol', source: 'dams', layout: { 'text-field': '▲', 'text-size': 11, 'text-allow-overlap': true }, paint: { 'text-color': '#f43f5e' } })
      for (const id of HIDDEN_AT_START) map.setLayoutProperty(id, 'visibility', 'none')
      setReady(true)
    })
    return () => { map.remove(); mapRef.current = null }
  }, [])

  // Stream reaches are tiled by HUC8 and added only when the layer is turned on.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !visible.streams) return
    for (const tile of tiles.data?.tiles ?? []) {
      const id = `streams-${tile}`
      if (map.getSource(id)) continue
      map.addSource(id, { type: 'geojson', data: hydroGeoUrl(id) })
      map.addLayer({ id, type: 'line', source: id, paint: { 'line-color': ['match', ['get', 'flow_type'], 'canal/ditch', '#94a3b8', '#38bdf8'], 'line-width': 0.7 } }, 'waterbodies-fill')
      LAYER_IDS.streams.push(id)
    }
  }, [ready, visible.streams, tiles.data])

  // NWI wetland polygons are tiled by HUC8 the same way, under the waterbodies.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !visible.wetlands) return
    for (const tile of tiles.data?.wetland_tiles ?? []) {
      const id = `wetlands-${tile}`
      if (map.getSource(id)) continue
      map.addSource(id, { type: 'geojson', data: hydroGeoUrl(id) })
      map.addLayer({ id, type: 'fill', source: id, paint: { 'fill-color': ['match', ['get', 'kind'], 'waterbody', '#0ea5e9', '#4d7c0f'], 'fill-opacity': 0.45 } }, 'waterbodies-fill')
      LAYER_IDS.wetlands.push(id)
    }
  }, [ready, visible.wetlands, tiles.data])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    for (const [key, ids] of Object.entries(LAYER_IDS)) {
      for (const id of ids) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible[key] ? 'visible' : 'none')
      }
    }
  }, [ready, visible])

  return (
    <div className="min-h-[360px] rounded-lg border border-slate-800 bg-slate-900/40 p-3" data-testid="hydro-map-workspace">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-200"><MapIcon className="h-4 w-4 text-sky-300" /> Hydrologic map workspace</div>
        <div role="group" aria-label="Map layers" className="flex flex-wrap gap-2 text-[11px] text-slate-400">
          {MAP_LAYERS.map((l) => (
            <label key={l.key} className="flex items-center gap-1">
              <input type="checkbox" checked={visible[l.key]} onChange={(e) => setVisible((v) => ({ ...v, [l.key]: e.target.checked }))} />
              {l.label}
            </label>
          ))}
        </div>
      </div>
      {OFFLINE || failed ? (
        <div className="flex h-[300px] items-center justify-center rounded border border-dashed border-slate-700 text-[11px] text-slate-500">
          {OFFLINE ? 'The map needs the backend; the offline export has no hydrologic geometry.' : `Map unavailable: ${failed}`}
        </div>
      ) : (
        <div ref={containerRef} className="h-[340px] w-full overflow-hidden rounded" aria-label="Hydrologic map" />
      )}
      {layerErrors.length > 0 && (
        <div role="alert" className="mt-2 rounded border border-red-900/50 bg-red-950/20 p-2 text-[11px] text-red-300">
          Some map layers did not load: {layerErrors.join('; ')}
        </div>
      )}
      <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
        Only geometry published by the sources is drawn (USGS HA 730-N aquifers, NHD streams, canals (grey) and waterbodies, WBD watersheds, USFWS NWI wetlands, located wells, springs and gauges, USACE NID dams, PRASA facilities and EPA-permitted wastewater plants). Wells: green monitored now, amber historical only, grey no readings; a white ring means USGS assigns the well to an aquifer. PRASA facility points come from PRASA's public May 2020 layer; NWI wetland mapping is largely from 1980s imagery. Features whose source publishes no location, such as SDWIS wells, intakes and treatment plants, are listed on the Hydro Inventory page and never placed.
      </p>
    </div>
  )
}
