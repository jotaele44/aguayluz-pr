import { Activity } from 'lucide-react'

export const MYCELIAL_LAYER_IDS = [
  'mycelial-grid-fill',
  'mycelial-observation-dot',
]

export function addMycelialMapLayers(map, observations, grid) {
  if (!map.getSource('mycelial-observations')) {
    map.addSource('mycelial-observations', {
      type: 'geojson',
      data: observations || { type: 'FeatureCollection', features: [] },
    })
  }
  if (!map.getSource('mycelial-grid')) {
    map.addSource('mycelial-grid', {
      type: 'geojson',
      data: grid || { type: 'FeatureCollection', features: [] },
    })
  }
  if (!map.getLayer('mycelial-grid-fill')) {
    map.addLayer({
      id: 'mycelial-grid-fill',
      type: 'circle',
      source: 'mycelial-grid',
      layout: { visibility: 'none' },
      paint: {
        'circle-radius': 11,
        'circle-color': '#22c55e',
        'circle-opacity': 0.22,
        'circle-stroke-color': '#14532d',
        'circle-stroke-width': 1,
      },
    })
  }
  if (!map.getLayer('mycelial-observation-dot')) {
    map.addLayer({
      id: 'mycelial-observation-dot',
      type: 'circle',
      source: 'mycelial-observations',
      layout: { visibility: 'none' },
      paint: {
        'circle-radius': 5,
        'circle-color': '#84cc16',
        'circle-opacity': 0.72,
        'circle-stroke-color': '#052e16',
        'circle-stroke-width': 1,
      },
    })
  }
}

export function setMycelialLayerVisibility(map, { precise = false, grid = false } = {}) {
  if (map.getLayer('mycelial-observation-dot')) {
    map.setLayoutProperty('mycelial-observation-dot', 'visibility', precise ? 'visible' : 'none')
  }
  if (map.getLayer('mycelial-grid-fill')) {
    map.setLayoutProperty('mycelial-grid-fill', 'visibility', grid ? 'visible' : 'none')
  }
}

export default function MycelialLayerLegend() {
  return (
    <div className="flex items-center gap-1.5 text-[10px] text-lime-300">
      <Activity className="h-3 w-3" />
      Mycelial observation layers are research-only and source-attributed.
    </div>
  )
}
