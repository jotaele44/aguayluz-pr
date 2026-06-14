import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'

// MapLibre map of utility assets over PR municipio boundaries. Assets colored by
// asset_type. Same wrapper pattern as the template — container is h-full (NOT
// absolute inset-0; maplibre-gl.css would override `absolute` and collapse it).
const OSM_STYLE = {
  version: 8,
  sources: {
    osm: { type: 'raster', tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors' },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#0b1220' } },
    { id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-opacity': 0.85, 'raster-saturation': -0.3 } },
  ],
}
const EMPTY = { type: 'FeatureCollection', features: [] }
const PR_CENTER = [-66.4, 18.22]

const TYPE_COLOR = [
  'match', ['get', 'asset_type'],
  'power', '#f59e0b', 'water', '#38bdf8', 'wastewater', '#10b981',
  'telecom', '#a78bfa', 'fuel', '#fb7185',
  '#64748b',
]

export default function AssetMap({ assets, municipios, onSelect }) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const readyRef = useRef(false)
  const assetsRef = useRef(assets); assetsRef.current = assets
  const muniRef = useRef(municipios); muniRef.current = municipios
  const onSelectRef = useRef(onSelect); onSelectRef.current = onSelect

  useEffect(() => {
    const map = new maplibregl.Map({ container: containerRef.current, style: OSM_STYLE, center: PR_CENTER, zoom: 8.2 })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    map.on('load', () => {
      map.addSource('municipios', { type: 'geojson', data: muniRef.current || EMPTY })
      map.addSource('assets', { type: 'geojson', data: assetsRef.current || EMPTY })
      map.addLayer({
        id: 'muni-line', type: 'line', source: 'municipios',
        paint: { 'line-color': '#334155', 'line-width': 0.8, 'line-opacity': 0.7 },
      })
      map.addLayer({
        id: 'assets-dot', type: 'circle', source: 'assets',
        paint: {
          'circle-radius': 4.5,
          'circle-color': TYPE_COLOR,
          'circle-opacity': 0.85,
          'circle-stroke-color': '#0b1220',
          'circle-stroke-width': 0.8,
        },
      })
      readyRef.current = true
      map.on('mouseenter', 'assets-dot', () => (map.getCanvas().style.cursor = 'pointer'))
      map.on('mouseleave', 'assets-dot', () => (map.getCanvas().style.cursor = ''))
      map.on('click', 'assets-dot', (e) => onSelectRef.current?.(e.features[0].properties))
    })
    return () => { readyRef.current = false; map.remove() }
  }, [])

  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('assets')?.setData(assets || EMPTY)
  }, [assets])
  useEffect(() => {
    if (!readyRef.current || !mapRef.current) return
    mapRef.current.getSource('municipios')?.setData(municipios || EMPTY)
  }, [municipios])

  return <div ref={containerRef} className="h-full w-full" />
}
