import {
  forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState,
} from 'react'
import * as maplibregl from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { Layers } from 'lucide-react'

maplibregl.setWorkerUrl(maplibreWorkerUrl)

const EMPTY = { type: 'FeatureCollection', features: [] }
const PR_CENTER = [-66.4, 18.22]
const CATEGORY_COLORS = {
  D0: '#ffff00',
  D1: '#fcd37f',
  D2: '#ffaa00',
  D3: '#e60000',
  D4: '#730000',
}
const DROUGHT_FILL = [
  'match', ['get', 'category'],
  'D0', CATEGORY_COLORS.D0,
  'D1', CATEGORY_COLORS.D1,
  'D2', CATEGORY_COLORS.D2,
  'D3', CATEGORY_COLORS.D3,
  'D4', CATEGORY_COLORS.D4,
  '#334155',
]
const RAIN_FILL = [
  'case', ['==', ['feature-state', 'rain_in'], null], 'rgba(0,0,0,0)',
  ['step', ['feature-state', 'rain_in'],
    '#334155',
    0.1, '#7dd3fc',
    0.5, '#38bdf8',
    1, '#2563eb',
    2, '#7c3aed',
    3, '#db2777',
  ],
]
const BASE_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#07111f' } }],
}

function pointCollection(rows, mapper) {
  const features = []
  for (const row of rows || []) {
    const mapped = mapper(row)
    if (mapped) features.push(mapped)
  }
  return { type: 'FeatureCollection', features }
}

function directOutageFeatures(events) {
  return pointCollection(events, (event) => {
    const lat = Number(event?.lat)
    const lon = Number(event?.lon)
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null
    return {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [lon, lat] },
      properties: {
        event_id: event.event_id,
        municipality: event.municipality,
        source_title: event.source_title || event.event_type || 'Outage',
        coordinate_source: 'direct_event_coordinates',
      },
    }
  })
}

function waterAssetFeatures(assets) {
  return {
    type: 'FeatureCollection',
    features: (assets?.features || []).filter((feature) => (
      feature?.properties?.asset_type === 'water'
      && Array.isArray(feature?.geometry?.coordinates)
    )),
  }
}

function latestGaugeTime(gauges) {
  const times = (gauges?.features || [])
    .map((feature) => feature?.properties?.valid_time)
    .filter(Boolean)
    .sort()
  return times.at(-1) || null
}

function ControlButton({ active, children, onClick }) {
  return (
    <button
      type="button"
      aria-pressed={Boolean(active)}
      onClick={onClick}
      className={`rounded border px-2 py-1 text-[11px] transition ${
        active
          ? 'border-sky-500/50 bg-sky-500/10 text-sky-200'
          : 'border-slate-700 bg-slate-950/75 text-slate-400 hover:text-slate-200'
      }`}
    >
      {children}
    </button>
  )
}

const DroughtMap = forwardRef(function DroughtMap({
  footprint,
  municipios,
  assets,
  gauges,
  alerts,
  outageEvents,
  rainByGeoid,
  mapDate,
  statistics,
  selectedMunicipio,
  onMunicipioSelect,
  onFootprintSelect,
}, ref) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const [ready, setReady] = useState(false)
  const [layers, setLayers] = useState({
    footprint: true,
    rainfall: false,
    water: true,
    gauges: true,
    outages: true,
    alerts: true,
  })
  const rainGeoidsRef = useRef(new Set())

  const water = useMemo(() => waterAssetFeatures(assets), [assets])
  const outages = useMemo(() => directOutageFeatures(outageEvents), [outageEvents])
  const alertGeo = alerts || EMPTY
  const gaugeGeo = gauges || EMPTY

  useEffect(() => {
    if (!containerRef.current) return undefined
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: PR_CENTER,
      zoom: 8.35,
      minZoom: 7.2,
      maxZoom: 13,
      preserveDrawingBuffer: true,
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    const onStyleLoad = () => {
      map.addSource('usdm-footprint', { type: 'geojson', data: footprint || EMPTY })
      map.addSource('municipios', {
        type: 'geojson',
        data: municipios || EMPTY,
        promoteId: 'geoid',
      })
      map.addSource('water-assets', { type: 'geojson', data: water })
      map.addSource('drought-gauges', { type: 'geojson', data: gaugeGeo })
      map.addSource('drought-alerts', { type: 'geojson', data: alertGeo })
      map.addSource('drought-outages', { type: 'geojson', data: outages })

      map.addLayer({
        id: 'drought-footprint-fill',
        type: 'fill',
        source: 'usdm-footprint',
        paint: { 'fill-color': DROUGHT_FILL, 'fill-opacity': 0.76 },
      })
      map.addLayer({
        id: 'drought-footprint-line',
        type: 'line',
        source: 'usdm-footprint',
        paint: { 'line-color': '#111827', 'line-width': 0.75, 'line-opacity': 0.7 },
      })
      map.addLayer({
        id: 'rainfall-fill',
        type: 'fill',
        source: 'municipios',
        layout: { visibility: 'none' },
        paint: { 'fill-color': RAIN_FILL, 'fill-opacity': 0.58 },
      })
      map.addLayer({
        id: 'municipio-hit',
        type: 'fill',
        source: 'municipios',
        paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.001 },
      })
      map.addLayer({
        id: 'municipio-lines',
        type: 'line',
        source: 'municipios',
        paint: {
          'line-color': [
            'case',
            ['==', ['get', 'name'], selectedMunicipio || ''],
            '#e2e8f0',
            '#0f172a',
          ],
          'line-width': [
            'case',
            ['==', ['get', 'name'], selectedMunicipio || ''],
            2.2,
            0.75,
          ],
          'line-opacity': 0.88,
        },
      })
      map.addLayer({
        id: 'water-assets',
        type: 'circle',
        source: 'water-assets',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 3.2, 11, 6],
          'circle-color': '#38bdf8',
          'circle-opacity': 0.88,
          'circle-stroke-color': '#082f49',
          'circle-stroke-width': 1,
        },
      })
      map.addLayer({
        id: 'drought-gauges',
        type: 'circle',
        source: 'drought-gauges',
        paint: {
          'circle-radius': 5,
          'circle-color': ['case', ['get', 'observation_stale'], '#64748b', '#22c55e'],
          'circle-stroke-color': '#020617',
          'circle-stroke-width': 1,
        },
      })
      map.addLayer({
        id: 'drought-outages',
        type: 'circle',
        source: 'drought-outages',
        paint: {
          'circle-radius': 7,
          'circle-color': '#f43f5e',
          'circle-opacity': 0.7,
          'circle-stroke-color': '#fef2f2',
          'circle-stroke-width': 1.2,
        },
      })
      map.addLayer({
        id: 'drought-alerts',
        type: 'circle',
        source: 'drought-alerts',
        paint: {
          'circle-radius': 6,
          'circle-color': '#fb923c',
          'circle-opacity': 0.72,
          'circle-stroke-color': '#fff7ed',
          'circle-stroke-width': 1.2,
        },
      })

      map.on('click', 'municipio-hit', (event) => {
        const props = event.features?.[0]?.properties
        if (props?.name) onMunicipioSelect?.(props)
      })
      map.on('click', 'drought-footprint-fill', (event) => {
        const props = event.features?.[0]?.properties
        if (props?.category) onFootprintSelect?.(props)
      })
      for (const layer of ['municipio-hit', 'drought-footprint-fill']) {
        map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer' })
        map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = '' })
      }
      setReady(true)
    }
    map.on('style.load', onStyleLoad)

    return () => {
      setReady(false)
      map.remove()
      mapRef.current = null
    }
  }, []) // Map sources are updated below; do not rebuild the WebGL context.

  useEffect(() => {
    if (!ready) return
    mapRef.current?.getSource('usdm-footprint')?.setData(footprint || EMPTY)
  }, [footprint, ready])

  useEffect(() => {
    if (!ready) return
    mapRef.current?.getSource('municipios')?.setData(municipios || EMPTY)
  }, [municipios, ready])

  useEffect(() => {
    if (!ready) return
    mapRef.current?.getSource('water-assets')?.setData(water)
  }, [water, ready])

  useEffect(() => {
    if (!ready) return
    mapRef.current?.getSource('drought-gauges')?.setData(gaugeGeo)
  }, [gaugeGeo, ready])

  useEffect(() => {
    if (!ready) return
    mapRef.current?.getSource('drought-alerts')?.setData(alertGeo)
  }, [alertGeo, ready])

  useEffect(() => {
    if (!ready) return
    mapRef.current?.getSource('drought-outages')?.setData(outages)
  }, [outages, ready])

  useEffect(() => {
    if (!ready || !mapRef.current) return undefined
    const map = mapRef.current
    const apply = () => {
      try {
        for (const geoid of rainGeoidsRef.current) {
          map.removeFeatureState({ source: 'municipios', id: geoid }, 'rain_in')
        }
        rainGeoidsRef.current.clear()
        for (const [geoid, value] of Object.entries(rainByGeoid || {})) {
          if (!Number.isFinite(Number(value))) continue
          map.setFeatureState({ source: 'municipios', id: geoid }, { rain_in: Number(value) })
          rainGeoidsRef.current.add(geoid)
        }
      } catch {
        // Source reload races are retried on sourcedata.
      }
    }
    const onSourceData = (event) => {
      if (event.sourceId === 'municipios' && event.isSourceLoaded) apply()
    }
    apply()
    map.on('sourcedata', onSourceData)
    return () => map.off('sourcedata', onSourceData)
  }, [rainByGeoid, ready, municipios])

  useEffect(() => {
    if (!ready || !mapRef.current) return
    const map = mapRef.current
    const visibility = (on) => (on ? 'visible' : 'none')
    map.setLayoutProperty('drought-footprint-fill', 'visibility', visibility(layers.footprint))
    map.setLayoutProperty('drought-footprint-line', 'visibility', visibility(layers.footprint))
    map.setLayoutProperty('rainfall-fill', 'visibility', visibility(layers.rainfall))
    map.setLayoutProperty('water-assets', 'visibility', visibility(layers.water))
    map.setLayoutProperty('drought-gauges', 'visibility', visibility(layers.gauges))
    map.setLayoutProperty('drought-outages', 'visibility', visibility(layers.outages))
    map.setLayoutProperty('drought-alerts', 'visibility', visibility(layers.alerts))
  }, [layers, ready])

  useEffect(() => {
    if (!ready || !mapRef.current) return
    mapRef.current.setPaintProperty('municipio-lines', 'line-color', [
      'case',
      ['==', ['get', 'name'], selectedMunicipio || ''],
      '#e2e8f0',
      '#0f172a',
    ])
    mapRef.current.setPaintProperty('municipio-lines', 'line-width', [
      'case',
      ['==', ['get', 'name'], selectedMunicipio || ''],
      2.2,
      0.75,
    ])
  }, [selectedMunicipio, ready])

  useImperativeHandle(ref, () => ({
    exportSnapshot() {
      const map = mapRef.current
      if (!map) return false
      const source = map.getCanvas()
      const padding = 24
      const header = 86
      const footer = 78
      const output = document.createElement('canvas')
      output.width = source.width
      output.height = source.height + header + footer
      const context = output.getContext('2d')
      if (!context) return false

      context.fillStyle = '#020617'
      context.fillRect(0, 0, output.width, output.height)
      context.fillStyle = '#f8fafc'
      context.font = '600 24px system-ui, sans-serif'
      context.fillText('AguaYLuz · Puerto Rico Drought Operations', padding, 34)
      context.fillStyle = '#94a3b8'
      context.font = '14px system-ui, sans-serif'
      context.fillText(`USDM map date ${mapDate || 'unavailable'} · weekly broad-scale analysis`, padding, 60)
      context.drawImage(source, 0, header)

      let x = padding
      const y = source.height + header + 30
      for (const category of ['D0', 'D1', 'D2', 'D3', 'D4']) {
        context.fillStyle = CATEGORY_COLORS[category]
        context.fillRect(x, y - 13, 16, 16)
        context.fillStyle = '#cbd5e1'
        context.font = '13px system-ui, sans-serif'
        const pct = statistics?.[category]
        const label = `${category} ${Number.isFinite(Number(pct)) ? `${Number(pct).toFixed(1)}%` : '—'}`
        context.fillText(label, x + 22, y)
        x += 112
      }
      context.fillStyle = '#64748b'
      context.font = '11px system-ui, sans-serif'
      context.fillText(
        `Water assets ${water.features.length} · gauges ${gaugeGeo.features?.length || 0} · direct outage points ${outages.features.length} · latest gauge ${latestGaugeTime(gaugeGeo) || '—'}`,
        padding,
        source.height + header + 58,
      )

      output.toBlob((blob) => {
        if (!blob) return
        const url = URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = `aguayluz-drought-${mapDate || 'unknown'}.png`
        anchor.click()
        URL.revokeObjectURL(url)
      }, 'image/png')
      return true
    },
  }), [gaugeGeo, mapDate, outages.features.length, statistics, water.features.length])

  return (
    <div className="relative h-full min-h-[520px] w-full overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
      <div ref={containerRef} className="h-full w-full" data-map-ready={ready ? 'true' : 'false'} />

      <div className="absolute left-3 top-3 max-w-[340px] rounded-xl border border-slate-700/70 bg-slate-950/90 p-3 shadow-xl backdrop-blur">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-100">
          <Layers className="h-3.5 w-3.5 text-sky-300" />
          Drought operations layers
        </div>
        <div className="flex flex-wrap gap-1.5">
          {[
            ['footprint', 'USDM footprint'],
            ['rainfall', 'Rainfall tint'],
            ['water', `Water assets ${water.features.length}`],
            ['gauges', `Gauges ${gaugeGeo.features?.length || 0}`],
            ['outages', `Direct outages ${outages.features.length}`],
            ['alerts', `Alerts ${alertGeo.features?.length || 0}`],
          ].map(([key, label]) => (
            <ControlButton
              key={key}
              active={layers[key]}
              onClick={() => setLayers((state) => ({ ...state, [key]: !state[key] }))}
            >
              {label}
            </ControlButton>
          ))}
        </div>
        <div className="mt-2 text-[10px] leading-relaxed text-slate-500">
          Outage markers require direct event coordinates. Rationing is not mapped until an authoritative geospatial feed is registered.
        </div>
      </div>

      <div className="absolute bottom-3 left-3 rounded-lg border border-slate-700/70 bg-slate-950/90 px-3 py-2 shadow-xl backdrop-blur">
        <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">USDM intensity</div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {Object.entries(CATEGORY_COLORS).map(([category, color]) => (
            <div key={category} className="flex items-center gap-1.5 text-[11px] text-slate-200">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
              {category}
            </div>
          ))}
        </div>
      </div>

      <div className="absolute bottom-3 right-3 rounded-lg border border-slate-700/70 bg-slate-950/90 px-3 py-2 text-[10px] text-slate-400 shadow-xl backdrop-blur">
        USDM {mapDate || 'unavailable'} · municipios selectable
      </div>
    </div>
  )
})

export default DroughtMap
