import { useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { Activity, Layers, MapPinned, Satellite } from 'lucide-react'

// Resolve against the configured base so it works in the normal build
// (served from '/') and the VITE_OFFLINE single-file file:// export (base './').
const MUNICIPIOS_URL = new URL('geo/pr_municipios.geojson', document.baseURI).href
const BARRIOS_URL = new URL('geo/pr_barrios.geojson', document.baseURI).href

const BASE_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
    satellite: {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      attribution: '© Esri World Imagery',
    },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#020617' } },
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
      paint: {
        'raster-opacity': 0.74,
        'raster-saturation': -0.72,
        'raster-contrast': -0.15,
        'raster-brightness-max': 0.68,
      },
    },
    {
      id: 'satellite',
      type: 'raster',
      source: 'satellite',
      layout: { visibility: 'none' },
      paint: { 'raster-opacity': 0.9 },
    },
  ],
}

const EMPTY = { type: 'FeatureCollection', features: [] }
const PR_CENTER = [-66.4, 18.22]
const TYPE_HEX = {
  power: '#f59e0b',
  water: '#38bdf8',
  wastewater: '#10b981',
  telecom: '#a78bfa',
  fuel: '#fb7185',
  other: '#64748b',
}
const TYPE_COLOR = [
  'match', ['get', 'asset_type'],
  'power', TYPE_HEX.power,
  'water', TYPE_HEX.water,
  'wastewater', TYPE_HEX.wastewater,
  'telecom', TYPE_HEX.telecom,
  'fuel', TYPE_HEX.fuel,
  TYPE_HEX.other,
]

// Operational alert severity (0-5) -> marker color. Matches alertSeverityMeta() in
// lib/format.js so the map legend and the alerts list read the same.
const SEVERITY_COLOR = [
  'match', ['to-string', ['get', 'severity']],
  '5', '#dc2626',
  '4', '#ef4444',
  '3', '#fb923c',
  '2', '#f59e0b',
  '1', '#94a3b8',
  '#64748b',
]

// Drought category (-1 = no designation, 0-4 = USDM D0-D4) -> municipio fill color.
// Mirrors droughtCategoryMeta()'s dot colors in lib/format.js exactly, the same way
// SEVERITY_COLOR above duplicates alertSeverityMeta() rather than importing it (MapLibre
// paint expressions can't call JS functions). Feature-state is only set for municipios
// MapPage.jsx actually has a drought reading for (`droughtByGeoid`); anything else keeps
// the flat outline fill so "no data fetched yet" never reads as "no drought designation".
const NO_DROUGHT_DATA_FILL = '#0f172a'
const DROUGHT_FILL_COLOR = [
  'case', ['==', ['feature-state', 'drought_category'], null], NO_DROUGHT_DATA_FILL,
  ['match', ['feature-state', 'drought_category'],
    -1, '#64748b',
    0, '#ffff00',
    1, '#fcd37f',
    2, '#ffaa00',
    3, '#e60000',
    4, '#730000',
    NO_DROUGHT_DATA_FILL,
  ],
]
// Matches the base look (flat, barely-there wash) until a municipio actually has a
// drought reading, then reads as an intentional tint rather than a color glitch.
const DROUGHT_FILL_OPACITY = [
  'case', ['==', ['feature-state', 'drought_category'], null], 0.08,
  0.55,
]

// Event-count choropleth for GET /municipios/event_density. Breaks are quartile-based
// against the actual corpus (78 municipios, counts ranging 1-1851, quartiles ~78/193/445)
// rather than round numbers, so the four buckets are roughly equal-sized rather than
// mostly-one-color. Same null-safe pattern as DROUGHT_FILL_COLOR: a municipio with no
// aggregate yet (endpoint not loaded, or genuinely zero events) keeps the flat wash.
const EVENT_DENSITY_FILL_COLOR = [
  'case', ['==', ['feature-state', 'event_count'], null], NO_DROUGHT_DATA_FILL,
  ['step', ['feature-state', 'event_count'],
    '#1e3a5f',
    80, '#2563eb',
    200, '#f59e0b',
    450, '#dc2626',
  ],
]
const EVENT_DENSITY_FILL_OPACITY = [
  'case', ['==', ['feature-state', 'event_count'], null], 0.08,
  0.55,
]

// MapLibre's setHTML parses its argument as HTML, and popup content comes from
// ingested records — an alert's source_title originates in a third-party feed
// (Centinelas/news/regulatory), so an `<img onerror=...>` in a headline would
// execute in the dashboard's origin. Escape every interpolated value.
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

function featureId(feature) {
  return feature?.properties?.asset_id ?? feature?.properties?.id
}

function averageCoordinates(features) {
  const pts = features
    .map((f) => f?.geometry?.coordinates)
    .filter((c) => Array.isArray(c) && Number.isFinite(c[0]) && Number.isFinite(c[1]))
  if (!pts.length) return null
  return [pts.reduce((sum, c) => sum + c[0], 0) / pts.length, pts.reduce((sum, c) => sum + c[1], 0) / pts.length]
}

function directEventCoordinates(event) {
  const lat = Number(event?.lat)
  const lon = Number(event?.lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null
  return [lon, lat]
}

export function eventFeatureCollection(events, assetRows, assetFeatures) {
  const byAsset = new Map(assetFeatures.map((f) => [featureId(f), f]))
  const byMunicipio = new Map()
  for (const f of assetFeatures) {
    const municipio = f?.properties?.municipality
    if (!municipio) continue
    if (!byMunicipio.has(municipio)) byMunicipio.set(municipio, [])
    byMunicipio.get(municipio).push(f)
  }
  const rowsByAsset = new Map(assetRows.map((a) => [a.asset_id, a]))

  const features = []
  for (const event of events || []) {
    let coords = directEventCoordinates(event)
    let coordinateSource = coords ? 'direct_event_coordinates' : null
    let coordConfidence = coords ? 'exact' : null
    if (!coords) {
      const linked = event.linked_asset_ids || []
      for (const id of linked) {
        const f = byAsset.get(id) || byAsset.get(rowsByAsset.get(id)?.asset_id)
        if (f?.geometry?.coordinates) {
          coords = f.geometry.coordinates
          coordinateSource = 'linked_asset'
          coordConfidence = 'approximate'
          break
        }
      }
    }
    if (!coords && event.municipality && byMunicipio.has(event.municipality)) {
      coords = averageCoordinates(byMunicipio.get(event.municipality))
      coordinateSource = coords ? 'municipality_asset_average' : null
      coordConfidence = coords ? 'approximate' : null
    }
    if (!coords) continue
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: coords },
      properties: {
        event_id: event.event_id,
        event_type: event.event_type,
        municipality: event.municipality,
        affected_area: event.affected_area,
        evidence_tier: event.evidence_tier,
        coordinate_source: coordinateSource,
        coord_confidence: coordConfidence,
        derived: coordinateSource !== 'direct_event_coordinates',
      },
    })
  }
  return { type: 'FeatureCollection', features }
}

function ControlButton({ active, children, onClick, tone }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded border px-2 py-1 text-[11px] transition ${active ? `${tone} bg-slate-900` : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'}`}
    >
      {children}
    </button>
  )
}

export default function AssetMap({ assets, assetRows = [], municipios, barrios, events = [], alerts, droughtByGeoid, eventDensityByGeoid, selectedAssetId, selectedMunicipio, onSelect, onMunicipioSelect, onAlertSelect, flyTo }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const readyRef = useRef(false)
  const onSelectRef = useRef(onSelect); onSelectRef.current = onSelect
  const onMunicipioSelectRef = useRef(onMunicipioSelect); onMunicipioSelectRef.current = onMunicipioSelect
  const onAlertSelectRef = useRef(onAlertSelect); onAlertSelectRef.current = onAlertSelect
  // Alerts start off: they are the densest layer (the SDWIS-derived contamination
  // history dominates), so they are opt-in rather than burying the asset dots.
  // muniFillMode replaces a boolean droughtTint: fill-color/fill-opacity are one paint
  // property each and can't honor two independent tints at once, so the municipio fill
  // is a single-select of 'off' | 'drought' | 'event_density' (drought stays the
  // pre-existing default). Barrios (sub-municipal boundaries) start off: event-density
  // data is only aggregated at municipio granularity today (see MapPage.jsx), so a
  // barrio outline alone would only add visual noise, not more signal.
  const [layers, setLayers] = useState({ power: true, water: true, wastewater: true, other: true, municipios: true, barrios: false, events: true, review: false, alerts: false, criticalAlertsOnly: false, muniFillMode: 'drought' })
  const [basemap, setBasemap] = useState('osm')

  const assetFeatures = assets?.features ?? []
  const visibleAssets = useMemo(() => {
    const enabled = new Set(Object.entries(layers).filter(([, active]) => active).map(([k]) => k))
    const rowsById = new Map(assetRows.map((a) => [a.asset_id, a]))
    const features = assetFeatures.filter((f) => {
      const p = f.properties || {}
      const type = p.asset_type || 'other'
      const bucket = ['power', 'water', 'wastewater'].includes(type) ? type : 'other'
      if (!enabled.has(bucket)) return false
      if (layers.review) {
        const row = rowsById.get(p.asset_id) || p
        return row.review_status === 'needs_review' || row.status === 'needs_review'
      }
      return true
    })
    return { type: 'FeatureCollection', features }
  }, [assetFeatures, assetRows, layers])

  const selectedAsset = useMemo(() => {
    const match = assetFeatures.find((f) => featureId(f) === selectedAssetId)
    return { type: 'FeatureCollection', features: match ? [match] : [] }
  }, [assetFeatures, selectedAssetId])

  const eventGeo = useMemo(() => eventFeatureCollection(events, assetRows, assetFeatures), [events, assetRows, assetFeatures])

  // Alerts carry their own coordinates from the promoter, so unlike events they need
  // no asset/municipio approximation — only the critical filter.
  const alertGeo = useMemo(() => {
    const features = alerts?.features ?? []
    return {
      type: 'FeatureCollection',
      features: layers.criticalAlertsOnly
        ? features.filter((f) => f.properties?.is_critical)
        : features,
    }
  }, [alerts, layers.criticalAlertsOnly])

  const counts = useMemo(() => {
    const base = { power: 0, water: 0, wastewater: 0, other: 0 }
    for (const f of assetFeatures) {
      const type = f.properties?.asset_type || 'other'
      base[['power', 'water', 'wastewater'].includes(type) ? type : 'other'] += 1
    }
    return base
  }, [assetFeatures])

  useEffect(() => {
    if (!containerRef.current) return undefined
    const map = new maplibregl.Map({ container: containerRef.current, style: BASE_STYLE, center: PR_CENTER, zoom: 8.25, minZoom: 7.2 })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    // 'style.load' instead of 'load': the latter waits for raster tiles,
    // which never resolve offline, and the data layers would never appear.
    map.on('style.load', () => {
      // promoteId lets MapLibre feature-state key off geoid directly, so drought tinting
      // (below) needs no client-side geometry mutation — just setFeatureState per geoid.
      map.addSource('municipios', { type: 'geojson', data: municipios || MUNICIPIOS_URL, promoteId: 'geoid' })
      map.addSource('barrios', { type: 'geojson', data: barrios || BARRIOS_URL })
      map.addSource('assets', { type: 'geojson', data: visibleAssets || EMPTY, cluster: true, clusterMaxZoom: 10, clusterRadius: 36 })
      map.addSource('selected-asset', { type: 'geojson', data: selectedAsset })
      map.addSource('service-events', { type: 'geojson', data: eventGeo })
      map.addSource('alert-events', { type: 'geojson', data: alertGeo })

      map.addLayer({
        id: 'muni-fill', type: 'fill', source: 'municipios',
        paint: { 'fill-color': DROUGHT_FILL_COLOR, 'fill-opacity': DROUGHT_FILL_OPACITY },
      })
      map.addLayer({
        id: 'muni-line', type: 'line', source: 'municipios',
        paint: { 'line-color': '#38bdf8', 'line-width': 0.7, 'line-opacity': 0.38 },
      })
      map.addLayer({
        id: 'barrios-line', type: 'line', source: 'barrios',
        layout: { visibility: 'none' },
        paint: { 'line-color': '#a78bfa', 'line-width': 0.5, 'line-opacity': 0.5, 'line-dasharray': [1, 1.5] },
      })
      map.addLayer({
        id: 'clusters', type: 'circle', source: 'assets', filter: ['has', 'point_count'],
        paint: {
          'circle-color': ['step', ['get', 'point_count'], '#0f766e', 30, '#2563eb', 80, '#f59e0b'],
          'circle-radius': ['step', ['get', 'point_count'], 14, 30, 18, 80, 24],
          'circle-opacity': 0.85,
          'circle-stroke-color': '#020617',
          'circle-stroke-width': 1,
        },
      })
      map.addLayer({
        id: 'cluster-count', type: 'symbol', source: 'assets', filter: ['has', 'point_count'],
        layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-size': 11 },
        paint: { 'text-color': '#f8fafc' },
      })
      map.addLayer({
        id: 'assets-dot', type: 'circle', source: 'assets', filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 3.5, 10, 4.8, 13, 7],
          'circle-color': TYPE_COLOR,
          'circle-opacity': 0.9,
          'circle-stroke-color': '#020617',
          'circle-stroke-width': 1.1,
        },
      })
      map.addLayer({
        id: 'events-dot', type: 'circle', source: 'service-events',
        paint: {
          'circle-radius': 8,
          'circle-color': '#ef4444',
          'circle-opacity': 0.55,
          'circle-stroke-color': '#fbbf24',
          'circle-stroke-width': 1.2,
        },
      })
      // Hollow diamonds-by-stroke so alerts stay distinguishable from the filled
      // asset dots and the red/amber event dots at every zoom.
      map.addLayer({
        id: 'alerts-dot', type: 'circle', source: 'alert-events',
        layout: { visibility: 'none' },
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 4, 10, 6, 13, 9],
          'circle-color': SEVERITY_COLOR,
          'circle-opacity': 0.28,
          'circle-stroke-color': SEVERITY_COLOR,
          'circle-stroke-width': ['case', ['get', 'is_critical'], 2.2, 1.2],
        },
      })
      map.addLayer({
        id: 'selected-ring', type: 'circle', source: 'selected-asset',
        paint: {
          'circle-radius': 11,
          'circle-color': 'rgba(56,189,248,0.08)',
          'circle-stroke-color': '#e0f2fe',
          'circle-stroke-width': 2.4,
        },
      })

      readyRef.current = true
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 })
      map.on('mouseenter', 'assets-dot', (e) => {
        map.getCanvas().style.cursor = 'pointer'
        const p = e.features[0]?.properties || {}
        popup.setLngLat(e.features[0].geometry.coordinates)
          .setHTML(`<div style="font:12px/1.5 system-ui,sans-serif;color:#e2e8f0;background:#0f172a;padding:6px 8px;border-radius:6px;max-width:200px"><strong>${esc(p.asset_name || 'Asset')}</strong><br/><span style="color:#94a3b8;font-size:11px">${esc((p.asset_type || 'unknown').replace(/_/g,' '))} · ${esc(p.municipality || '')}</span></div>`)
          .addTo(map)
      })
      map.on('mouseleave', 'assets-dot', () => {
        map.getCanvas().style.cursor = ''
        popup.remove()
      })
      map.on('mouseenter', 'alerts-dot', (e) => {
        map.getCanvas().style.cursor = 'pointer'
        const p = e.features[0]?.properties || {}
        popup.setLngLat(e.features[0].geometry.coordinates)
          .setHTML(`<div style="font:12px/1.5 system-ui,sans-serif;color:#e2e8f0;background:#0f172a;padding:6px 8px;border-radius:6px;max-width:220px"><strong>${esc(p.source_title || p.alert_id || 'Alert')}</strong><br/><span style="color:#94a3b8;font-size:11px">${esc(p.module_id || 'alert')} · severity ${esc(p.severity ?? '—')} · ${esc(p.status || '')}</span></div>`)
          .addTo(map)
      })
      map.on('mouseleave', 'alerts-dot', () => {
        map.getCanvas().style.cursor = ''
        popup.remove()
      })
      map.on('click', 'alerts-dot', (e) => onAlertSelectRef.current?.(e.features[0].properties))
      map.on('click', 'assets-dot', (e) => onSelectRef.current?.(e.features[0].properties))
      map.on('click', 'clusters', async (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: ['clusters'] })
        const clusterId = features[0]?.properties?.cluster_id
        if (clusterId == null) return
        const zoom = await map.getSource('assets').getClusterExpansionZoom(clusterId)
        map.easeTo({ center: features[0].geometry.coordinates, zoom })
      })
      map.on('click', 'muni-fill', (e) => {
        const props = e.features?.[0]?.properties || {}
        onMunicipioSelectRef.current?.({ name: props.name || props.NAME || props.municipio || props.MUNICIPIO, properties: props })
      })
    })
    return () => { readyRef.current = false; map.remove() }
  }, [])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('assets')?.setData(visibleAssets || EMPTY)
  }, [visibleAssets])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current || !flyTo) return
    mapRef.current.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: 14, duration: 1200 })
  }, [flyTo?.id])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('municipios')?.setData(municipios || EMPTY)
  }, [municipios])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('barrios')?.setData(barrios || EMPTY)
  }, [barrios])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    // Also re-run when `municipios` changes: the municipios source's own setData() effect
    // (above) can resolve after this one already applied feature-state, and MapLibre's
    // GeoJSON source rebuilds its internal feature ids on setData — any state set before
    // that rebuild is lost, so a real municipios update must trigger a re-apply here too.
    for (const [geoid, category] of Object.entries(droughtByGeoid || {})) {
      mapRef.current.setFeatureState({ source: 'municipios', id: geoid }, { drought_category: category })
    }
  }, [droughtByGeoid, municipios])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    // Same re-apply-on-municipios-change reasoning as the drought effect above.
    for (const [geoid, count] of Object.entries(eventDensityByGeoid || {})) {
      mapRef.current.setFeatureState({ source: 'municipios', id: geoid }, { event_count: count })
    }
  }, [eventDensityByGeoid, municipios])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('selected-asset')?.setData(selectedAsset)
    const coords = selectedAsset.features?.[0]?.geometry?.coordinates
    if (coords) mapRef.current.easeTo({ center: coords, duration: 450 })
  }, [selectedAsset])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('service-events')?.setData(eventGeo)
  }, [eventGeo])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('alert-events')?.setData(alertGeo)
  }, [alertGeo])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    const visibility = layers.municipios ? 'visible' : 'none'
    for (const id of ['muni-fill', 'muni-line']) mapRef.current.setLayoutProperty(id, 'visibility', visibility)
    mapRef.current.setLayoutProperty('barrios-line', 'visibility', layers.barrios ? 'visible' : 'none')
    mapRef.current.setLayoutProperty('events-dot', 'visibility', layers.events ? 'visible' : 'none')
    mapRef.current.setLayoutProperty('alerts-dot', 'visibility', layers.alerts ? 'visible' : 'none')
    const [fillColor, fillOpacity] = {
      drought: [DROUGHT_FILL_COLOR, DROUGHT_FILL_OPACITY],
      event_density: [EVENT_DENSITY_FILL_COLOR, EVENT_DENSITY_FILL_OPACITY],
      off: [NO_DROUGHT_DATA_FILL, 0.08],
    }[layers.muniFillMode]
    mapRef.current.setPaintProperty('muni-fill', 'fill-color', fillColor)
    mapRef.current.setPaintProperty('muni-fill', 'fill-opacity', fillOpacity)
  }, [layers.municipios, layers.barrios, layers.events, layers.alerts, layers.muniFillMode])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    try {
      mapRef.current.setLayoutProperty('osm', 'visibility', basemap === 'osm' ? 'visible' : 'none')
      mapRef.current.setLayoutProperty('satellite', 'visibility', basemap === 'satellite' ? 'visible' : 'none')
    } catch { /* layers may not be ready yet */ }
  }, [basemap])

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      <div className="absolute left-3 top-3 w-[250px] rounded-xl border border-slate-700/70 bg-slate-950/85 p-3 shadow-xl backdrop-blur">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-100"><Layers className="h-3.5 w-3.5 text-sky-300" /> Layers</div>
          <div className="text-[10px] text-slate-500">{visibleAssets.features.length}/{assetFeatures.length}</div>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <ControlButton active={layers.power} tone="border-amber-500/40 text-amber-300" onClick={() => setLayers((s) => ({ ...s, power: !s.power }))}>Power {counts.power}</ControlButton>
          <ControlButton active={layers.water} tone="border-sky-500/40 text-sky-300" onClick={() => setLayers((s) => ({ ...s, water: !s.water }))}>Water {counts.water}</ControlButton>
          <ControlButton active={layers.wastewater} tone="border-emerald-500/40 text-emerald-300" onClick={() => setLayers((s) => ({ ...s, wastewater: !s.wastewater }))}>Wastewater {counts.wastewater}</ControlButton>
          <ControlButton active={layers.other} tone="border-slate-500/40 text-slate-300" onClick={() => setLayers((s) => ({ ...s, other: !s.other }))}>Other {counts.other}</ControlButton>
          <ControlButton active={layers.municipios} tone="border-cyan-500/40 text-cyan-300" onClick={() => setLayers((s) => ({ ...s, municipios: !s.municipios }))}>Municipios</ControlButton>
          <ControlButton active={layers.barrios} tone="border-violet-500/40 text-violet-300" onClick={() => setLayers((s) => ({ ...s, barrios: !s.barrios }))}>Barrios</ControlButton>
          <ControlButton active={layers.events} tone="border-red-500/40 text-red-300" onClick={() => setLayers((s) => ({ ...s, events: !s.events }))}>Events (sample) {eventGeo.features.length}</ControlButton>
          <ControlButton active={layers.alerts} tone="border-orange-500/40 text-orange-300" onClick={() => setLayers((s) => ({ ...s, alerts: !s.alerts }))}>Alerts {alertGeo.features.length}</ControlButton>
        </div>
        <div className="mt-1.5">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">Municipio fill</div>
          <div className="grid grid-cols-3 gap-1.5">
            <ControlButton active={layers.muniFillMode === 'off'} tone="border-slate-500/40 text-slate-300" onClick={() => setLayers((s) => ({ ...s, muniFillMode: 'off' }))}>Off</ControlButton>
            <ControlButton active={layers.muniFillMode === 'drought'} tone="border-amber-500/40 text-amber-300" onClick={() => setLayers((s) => ({ ...s, muniFillMode: 'drought' }))}>Drought</ControlButton>
            <ControlButton active={layers.muniFillMode === 'event_density'} tone="border-blue-500/40 text-blue-300" onClick={() => setLayers((s) => ({ ...s, muniFillMode: 'event_density' }))}>Density</ControlButton>
          </div>
        </div>
        {layers.alerts && (
          <button
            type="button"
            aria-pressed={layers.criticalAlertsOnly}
            onClick={() => setLayers((s) => ({ ...s, criticalAlertsOnly: !s.criticalAlertsOnly }))}
            className={`mt-1.5 w-full rounded border px-2 py-1.5 text-[11px] transition ${layers.criticalAlertsOnly ? 'border-red-500/40 bg-red-500/10 text-red-300' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'}`}
          >
            Life-safety critical alerts only
          </button>
        )}
        <button
          type="button"
          aria-pressed={layers.review}
          onClick={() => setLayers((s) => ({ ...s, review: !s.review }))}
          className={`mt-2 w-full rounded border px-2 py-1.5 text-[11px] transition ${layers.review ? 'border-amber-500/40 bg-amber-500/10 text-amber-300' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'}`}
        >
          Review-needed assets only
        </button>
        <div className="mt-2 flex gap-1">
          <button
            type="button"
            onClick={() => setBasemap('osm')}
            className={`flex-1 flex items-center justify-center gap-1 rounded border px-2 py-1.5 text-[11px] transition ${basemap === 'osm' ? 'border-sky-500/40 bg-sky-500/10 text-sky-300' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'}`}
          >
            <Layers className="h-3 w-3" /> Map
          </button>
          <button
            type="button"
            onClick={() => setBasemap('satellite')}
            className={`flex-1 flex items-center justify-center gap-1 rounded border px-2 py-1.5 text-[11px] transition ${basemap === 'satellite' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'}`}
          >
            <Satellite className="h-3 w-3" /> Satellite
          </button>
        </div>
      </div>

      <div className="absolute bottom-3 left-3 rounded-lg border border-slate-700/70 bg-slate-950/85 px-2.5 py-2 shadow-xl backdrop-blur">
        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5">Asset type</div>
        {[
          { type: 'power', label: 'Power', color: '#f59e0b' },
          { type: 'water', label: 'Water', color: '#38bdf8' },
          { type: 'wastewater', label: 'Wastewater', color: '#10b981' },
          { type: 'telecom', label: 'Telecom', color: '#a78bfa' },
          { type: 'other', label: 'Other', color: '#64748b' },
        ].map(({ type, label, color }) => (
          <div key={type} className="flex items-center gap-1.5 text-[11px] text-slate-300 mb-0.5 last:mb-0">
            <span style={{ background: color }} className="inline-block h-2 w-2 rounded-full shrink-0" />
            {label}
          </div>
        ))}
        {layers.alerts && (
          <>
            <div className="mb-1.5 mt-2 border-t border-slate-800 pt-2 text-[10px] uppercase tracking-wide text-slate-500">Alert severity</div>
            {[
              { sev: '4–5', label: 'Severe / extreme', color: '#ef4444' },
              { sev: '3', label: 'Elevated', color: '#fb923c' },
              { sev: '2', label: 'Moderate', color: '#f59e0b' },
              { sev: '0–1', label: 'Low / informational', color: '#94a3b8' },
            ].map(({ sev, label, color }) => (
              <div key={sev} className="mb-0.5 flex items-center gap-1.5 text-[11px] text-slate-300 last:mb-0">
                <span style={{ borderColor: color }} className="inline-block h-2 w-2 shrink-0 rounded-full border-2" />
                {label}
              </div>
            ))}
          </>
        )}
        {layers.muniFillMode === 'drought' && droughtByGeoid && Object.keys(droughtByGeoid).length > 0 && (
          <>
            {/* Only rendered once real drought readings exist — an empty-but-present
                legend would imply coverage the corpus doesn't have yet. */}
            <div className="mb-1.5 mt-2 border-t border-slate-800 pt-2 text-[10px] uppercase tracking-wide text-slate-500">Drought (USDM)</div>
            {[
              { label: 'D4 · Exceptional', color: '#730000' },
              { label: 'D3 · Extreme', color: '#e60000' },
              { label: 'D2 · Severe', color: '#ffaa00' },
              { label: 'D1 · Moderate', color: '#fcd37f' },
              { label: 'D0 · Abnormally dry', color: '#ffff00' },
              { label: 'No drought', color: '#64748b' },
            ].map(({ label, color }) => (
              <div key={label} className="mb-0.5 flex items-center gap-1.5 text-[11px] text-slate-300 last:mb-0">
                <span style={{ background: color }} className="inline-block h-2 w-2 rounded-full shrink-0" />
                {label}
              </div>
            ))}
          </>
        )}
        {layers.muniFillMode === 'event_density' && eventDensityByGeoid && Object.keys(eventDensityByGeoid).length > 0 && (
          <>
            <div className="mb-1.5 mt-2 border-t border-slate-800 pt-2 text-[10px] uppercase tracking-wide text-slate-500">Event density (full corpus)</div>
            {[
              { label: '450+ events', color: '#dc2626' },
              { label: '200–449', color: '#f59e0b' },
              { label: '80–199', color: '#2563eb' },
              { label: '1–79', color: '#1e3a5f' },
            ].map(({ label, color }) => (
              <div key={label} className="mb-0.5 flex items-center gap-1.5 text-[11px] text-slate-300 last:mb-0">
                <span style={{ background: color }} className="inline-block h-2 w-2 rounded-full shrink-0" />
                {label}
              </div>
            ))}
          </>
        )}
      </div>

      <div className="absolute right-3 bottom-3 max-w-[280px] rounded-xl border border-slate-700/70 bg-slate-950/85 p-3 shadow-xl backdrop-blur">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-100"><MapPinned className="h-3.5 w-3.5 text-sky-300" /> Map intelligence</div>
        <div className="mt-2 text-[11px] leading-relaxed text-slate-400">
          {selectedMunicipio?.name ? (
            <span><span className="text-slate-200">{selectedMunicipio.name}</span> selected. Asset/event overlays remain source-derived; event markers are municipio/asset-position approximations when exact event geometry is unavailable.</span>
          ) : (
            <span>Select a marker or municipio to pivot the asset table and detail drawer.</span>
          )}
        </div>
        {eventGeo.features.length > 0 && (
          <div className="mt-2 flex items-center gap-1.5 text-[10px] text-amber-300"><Activity className="h-3 w-3" /> Event dots are a recent/approximate sample — use the "Density" municipio fill for the full corpus.</div>
        )}
      </div>
    </div>
  )
}
