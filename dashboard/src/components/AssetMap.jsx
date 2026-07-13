import { useEffect, useMemo, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { Activity, Layers, MapPinned } from 'lucide-react'
import { useMycelialGridGeojson, useMycelialObservationsGeojson } from '@/lib/hooks'

// Resolve against the configured base so this works for normal hosting and the
// VITE_OFFLINE single-file export.
const MUNICIPIOS_URL = new URL('geo/pr_municipios.geojson', document.baseURI).href
const EMPTY = { type: 'FeatureCollection', features: [] }
const PR_CENTER = [-66.4, 18.22]

const OSM_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
    municipios: { type: 'geojson', data: MUNICIPIOS_URL },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#020617' } },
    { id: 'municipios-fill', type: 'fill', source: 'municipios', paint: { 'fill-color': '#0d1b30', 'fill-opacity': 0.9 } },
    { id: 'municipios-line', type: 'line', source: 'municipios', paint: { 'line-color': '#31507a', 'line-width': 0.8 } },
    {
      id: 'osm', type: 'raster', source: 'osm',
      paint: {
        'raster-opacity': 0.74,
        'raster-saturation': -0.72,
        'raster-contrast': -0.15,
        'raster-brightness-max': 0.68,
      },
    },
  ],
}

const TYPE_HEX = {
  power: '#f59e0b', water: '#38bdf8', wastewater: '#10b981',
  telecom: '#a78bfa', fuel: '#fb7185', other: '#64748b',
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

function featureId(feature) {
  return feature?.properties?.asset_id ?? feature?.properties?.id
}

function averageCoordinates(features) {
  const points = features
    .map((feature) => feature?.geometry?.coordinates)
    .filter((coords) => Array.isArray(coords) && Number.isFinite(coords[0]) && Number.isFinite(coords[1]))
  if (!points.length) return null
  return [
    points.reduce((sum, coords) => sum + coords[0], 0) / points.length,
    points.reduce((sum, coords) => sum + coords[1], 0) / points.length,
  ]
}

function eventFeatureCollection(events, assetRows, assetFeatures) {
  const byAsset = new Map(assetFeatures.map((feature) => [featureId(feature), feature]))
  const byMunicipio = new Map()
  for (const feature of assetFeatures) {
    const municipio = feature?.properties?.municipality
    if (!municipio) continue
    if (!byMunicipio.has(municipio)) byMunicipio.set(municipio, [])
    byMunicipio.get(municipio).push(feature)
  }
  const rowsByAsset = new Map(assetRows.map((asset) => [asset.asset_id, asset]))
  const features = []
  for (const event of events || []) {
    let coords = null
    for (const id of event.linked_asset_ids || []) {
      const feature = byAsset.get(id) || byAsset.get(rowsByAsset.get(id)?.asset_id)
      if (feature?.geometry?.coordinates) {
        coords = feature.geometry.coordinates
        break
      }
    }
    if (!coords && event.municipality && byMunicipio.has(event.municipality)) {
      coords = averageCoordinates(byMunicipio.get(event.municipality))
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
        derived: true,
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

export default function AssetMap({
  assets, assetRows = [], municipios, events = [], selectedAssetId,
  selectedMunicipio, onSelect, onMunicipioSelect,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const readyRef = useRef(false)
  const onSelectRef = useRef(onSelect); onSelectRef.current = onSelect
  const onMunicipioSelectRef = useRef(onMunicipioSelect); onMunicipioSelectRef.current = onMunicipioSelect
  const { data: mycelialObservations = EMPTY } = useMycelialObservationsGeojson()
  const { data: mycelialGrid = EMPTY } = useMycelialGridGeojson()
  const [layers, setLayers] = useState({
    power: true, water: true, wastewater: true, other: true,
    municipios: true, events: true, review: false,
    mycelialPrecise: false, mycelialGrid: false,
  })

  const assetFeatures = assets?.features ?? []
  const visibleAssets = useMemo(() => {
    const enabled = new Set(Object.entries(layers).filter(([, active]) => active).map(([key]) => key))
    const rowsById = new Map(assetRows.map((asset) => [asset.asset_id, asset]))
    return {
      type: 'FeatureCollection',
      features: assetFeatures.filter((feature) => {
        const props = feature.properties || {}
        const type = props.asset_type || 'other'
        const bucket = ['power', 'water', 'wastewater'].includes(type) ? type : 'other'
        if (!enabled.has(bucket)) return false
        if (!layers.review) return true
        const row = rowsById.get(props.asset_id) || props
        return row.review_status === 'needs_review' || row.status === 'needs_review'
      }),
    }
  }, [assetFeatures, assetRows, layers])

  const selectedAsset = useMemo(() => {
    const match = assetFeatures.find((feature) => featureId(feature) === selectedAssetId)
    return { type: 'FeatureCollection', features: match ? [match] : [] }
  }, [assetFeatures, selectedAssetId])
  const eventGeo = useMemo(
    () => eventFeatureCollection(events, assetRows, assetFeatures),
    [events, assetRows, assetFeatures],
  )
  const counts = useMemo(() => {
    const result = { power: 0, water: 0, wastewater: 0, other: 0 }
    for (const feature of assetFeatures) {
      const type = feature.properties?.asset_type || 'other'
      result[['power', 'water', 'wastewater'].includes(type) ? type : 'other'] += 1
    }
    return result
  }, [assetFeatures])

  useEffect(() => {
    if (!containerRef.current) return undefined
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: PR_CENTER,
      zoom: 8.25,
      minZoom: 7.2,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    // style.load does not wait for remote raster tiles, so data layers initialize offline.
    map.on('style.load', () => {
      map.addSource('assets', { type: 'geojson', data: visibleAssets || EMPTY, cluster: true, clusterMaxZoom: 10, clusterRadius: 36 })
      map.addSource('selected-asset', { type: 'geojson', data: selectedAsset })
      map.addSource('service-events', { type: 'geojson', data: eventGeo })
      map.addSource('mycelial-observations', { type: 'geojson', data: mycelialObservations || EMPTY })
      map.addSource('mycelial-grid', { type: 'geojson', data: mycelialGrid || EMPTY })

      map.addLayer({ id: 'muni-hit-area', type: 'fill', source: 'municipios', paint: { 'fill-color': '#0f172a', 'fill-opacity': 0.01 } })
      map.addLayer({
        id: 'mycelial-grid-fill', type: 'circle', source: 'mycelial-grid', layout: { visibility: 'none' },
        paint: { 'circle-radius': 11, 'circle-color': '#22c55e', 'circle-opacity': 0.22, 'circle-stroke-color': '#14532d', 'circle-stroke-width': 1 },
      })
      map.addLayer({
        id: 'clusters', type: 'circle', source: 'assets', filter: ['has', 'point_count'],
        paint: { 'circle-color': ['step', ['get', 'point_count'], '#0f766e', 30, '#2563eb', 80, '#f59e0b'], 'circle-radius': ['step', ['get', 'point_count'], 14, 30, 18, 80, 24], 'circle-opacity': 0.85, 'circle-stroke-color': '#020617', 'circle-stroke-width': 1 },
      })
      map.addLayer({ id: 'cluster-count', type: 'symbol', source: 'assets', filter: ['has', 'point_count'], layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-size': 11 }, paint: { 'text-color': '#f8fafc' } })
      map.addLayer({ id: 'assets-dot', type: 'circle', source: 'assets', filter: ['!', ['has', 'point_count']], paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 3.5, 10, 4.8, 13, 7], 'circle-color': TYPE_COLOR, 'circle-opacity': 0.9, 'circle-stroke-color': '#020617', 'circle-stroke-width': 1.1 } })
      map.addLayer({ id: 'events-dot', type: 'circle', source: 'service-events', paint: { 'circle-radius': 8, 'circle-color': '#ef4444', 'circle-opacity': 0.55, 'circle-stroke-color': '#fbbf24', 'circle-stroke-width': 1.2 } })
      map.addLayer({ id: 'mycelial-observation-dot', type: 'circle', source: 'mycelial-observations', layout: { visibility: 'none' }, paint: { 'circle-radius': 5, 'circle-color': '#84cc16', 'circle-opacity': 0.72, 'circle-stroke-color': '#052e16', 'circle-stroke-width': 1 } })
      map.addLayer({ id: 'selected-ring', type: 'circle', source: 'selected-asset', paint: { 'circle-radius': 11, 'circle-color': 'rgba(56,189,248,0.08)', 'circle-stroke-color': '#e0f2fe', 'circle-stroke-width': 2.4 } })

      readyRef.current = true
      map.on('mouseenter', 'assets-dot', () => (map.getCanvas().style.cursor = 'pointer'))
      map.on('mouseleave', 'assets-dot', () => (map.getCanvas().style.cursor = ''))
      map.on('click', 'assets-dot', (event) => onSelectRef.current?.(event.features[0].properties))
      map.on('click', 'clusters', async (event) => {
        const features = map.queryRenderedFeatures(event.point, { layers: ['clusters'] })
        const clusterId = features[0]?.properties?.cluster_id
        if (clusterId == null) return
        const zoom = await map.getSource('assets').getClusterExpansionZoom(clusterId)
        map.easeTo({ center: features[0].geometry.coordinates, zoom })
      })
      map.on('click', 'muni-hit-area', (event) => {
        const props = event.features?.[0]?.properties || {}
        onMunicipioSelectRef.current?.({
          name: props.name || props.NAME || props.municipio || props.MUNICIPIO,
          properties: props,
        })
      })
    })
    return () => { readyRef.current = false; map.remove() }
  }, [])

  useEffect(() => { if (readyRef.current) mapRef.current?.getSource('assets')?.setData(visibleAssets || EMPTY) }, [visibleAssets])
  useEffect(() => {
    if (!readyRef.current || !municipios) return
    mapRef.current?.getSource('municipios')?.setData(municipios)
  }, [municipios])
  useEffect(() => {
    if (!readyRef.current) return
    mapRef.current?.getSource('selected-asset')?.setData(selectedAsset)
    const coords = selectedAsset.features?.[0]?.geometry?.coordinates
    if (coords) mapRef.current?.easeTo({ center: coords, duration: 450 })
  }, [selectedAsset])
  useEffect(() => { if (readyRef.current) mapRef.current?.getSource('service-events')?.setData(eventGeo) }, [eventGeo])
  useEffect(() => { if (readyRef.current) mapRef.current?.getSource('mycelial-observations')?.setData(mycelialObservations || EMPTY) }, [mycelialObservations])
  useEffect(() => { if (readyRef.current) mapRef.current?.getSource('mycelial-grid')?.setData(mycelialGrid || EMPTY) }, [mycelialGrid])
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    const municipioVisibility = layers.municipios ? 'visible' : 'none'
    for (const id of ['municipios-fill', 'municipios-line', 'muni-hit-area']) {
      mapRef.current.setLayoutProperty(id, 'visibility', municipioVisibility)
    }
    mapRef.current.setLayoutProperty('events-dot', 'visibility', layers.events ? 'visible' : 'none')
    mapRef.current.setLayoutProperty('mycelial-observation-dot', 'visibility', layers.mycelialPrecise ? 'visible' : 'none')
    mapRef.current.setLayoutProperty('mycelial-grid-fill', 'visibility', layers.mycelialGrid ? 'visible' : 'none')
  }, [layers.municipios, layers.events, layers.mycelialPrecise, layers.mycelialGrid])

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      <div className="absolute left-3 top-3 w-[250px] rounded-xl border border-slate-700/70 bg-slate-950/85 p-3 shadow-xl backdrop-blur">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-100"><Layers className="h-3.5 w-3.5 text-sky-300" /> Layers</div>
          <div className="text-[10px] text-slate-500">{visibleAssets.features.length}/{assetFeatures.length}</div>
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          <ControlButton active={layers.power} tone="border-amber-500/40 text-amber-300" onClick={() => setLayers((state) => ({ ...state, power: !state.power }))}>Power {counts.power}</ControlButton>
          <ControlButton active={layers.water} tone="border-sky-500/40 text-sky-300" onClick={() => setLayers((state) => ({ ...state, water: !state.water }))}>Water {counts.water}</ControlButton>
          <ControlButton active={layers.wastewater} tone="border-emerald-500/40 text-emerald-300" onClick={() => setLayers((state) => ({ ...state, wastewater: !state.wastewater }))}>Wastewater {counts.wastewater}</ControlButton>
          <ControlButton active={layers.other} tone="border-slate-500/40 text-slate-300" onClick={() => setLayers((state) => ({ ...state, other: !state.other }))}>Other {counts.other}</ControlButton>
          <ControlButton active={layers.municipios} tone="border-cyan-500/40 text-cyan-300" onClick={() => setLayers((state) => ({ ...state, municipios: !state.municipios }))}>Municipios</ControlButton>
          <ControlButton active={layers.events} tone="border-red-500/40 text-red-300" onClick={() => setLayers((state) => ({ ...state, events: !state.events }))}>Events {eventGeo.features.length}</ControlButton>
          <ControlButton active={layers.mycelialPrecise} tone="border-lime-500/40 text-lime-300" onClick={() => setLayers((state) => ({ ...state, mycelialPrecise: !state.mycelialPrecise }))}>Mycelial precise {mycelialObservations?.features?.length ?? 0}</ControlButton>
          <ControlButton active={layers.mycelialGrid} tone="border-green-500/40 text-green-300" onClick={() => setLayers((state) => ({ ...state, mycelialGrid: !state.mycelialGrid }))}>Mycelial grid {mycelialGrid?.features?.length ?? 0}</ControlButton>
        </div>
        <button type="button" onClick={() => setLayers((state) => ({ ...state, review: !state.review }))} className={`mt-2 w-full rounded border px-2 py-1.5 text-[11px] transition ${layers.review ? 'border-amber-500/40 bg-amber-500/10 text-amber-300' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'}`}>Review-needed assets only</button>
      </div>
      <div className="absolute right-3 bottom-3 max-w-[280px] rounded-xl border border-slate-700/70 bg-slate-950/85 p-3 shadow-xl backdrop-blur">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-100"><MapPinned className="h-3.5 w-3.5 text-sky-300" /> Map intelligence</div>
        <div className="mt-2 text-[11px] leading-relaxed text-slate-400">
          {selectedMunicipio?.name ? <span><span className="text-slate-200">{selectedMunicipio.name}</span> selected. Asset/event overlays remain source-derived.</span> : <span>Select a marker or municipio to pivot the asset table and detail drawer.</span>}
        </div>
        {eventGeo.features.length > 0 && <div className="mt-2 flex items-center gap-1.5 text-[10px] text-amber-300"><Activity className="h-3 w-3" /> Event dots are derived from asset/municipio context.</div>}
        {(mycelialObservations?.features?.length ?? 0) > 0 && <div className="mt-2 flex items-center gap-1.5 text-[10px] text-lime-300"><Activity className="h-3 w-3" /> Mycelial observation dots are source-attributed research records.</div>}
      </div>
    </div>
  )
}
