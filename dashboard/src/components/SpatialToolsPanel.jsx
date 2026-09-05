import { useEffect, useState } from 'react'
import { point, featureCollection } from '@turf/helpers'
import turfLength from '@turf/length'
import turfDistance from '@turf/distance'
import turfCircle from '@turf/circle'
import booleanPointInPolygon from '@turf/boolean-point-in-polygon'
import turfNearestPoint from '@turf/nearest-point'

const MEASURE_SOURCE = 'tool-measure-line'
const BUFFER_SOURCE = 'tool-buffer-circle'
const NEAREST_SOURCE = 'tool-nearest-highlight'
const BUFFER_RADII_KM = [1, 5, 10, 25]

function ensureLineSource(map, id, color) {
  if (!map.getSource(id)) {
    map.addSource(id, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    map.addLayer({
      id: `${id}-line`, type: 'line', source: id,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': color, 'line-width': 2 },
    })
    map.addLayer({
      id: `${id}-points`, type: 'circle', source: id,
      filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-radius': 4, 'circle-color': color },
    })
  }
}

function ensureFillSource(map, id, color) {
  if (!map.getSource(id)) {
    map.addSource(id, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
    map.addLayer({
      id: `${id}-fill`, type: 'fill', source: id,
      paint: { 'fill-color': color, 'fill-opacity': 0.15 },
    })
    map.addLayer({
      id: `${id}-outline`, type: 'line', source: id,
      paint: { 'line-color': color, 'line-width': 1.5 },
    })
  }
}

function setSourceData(map, id, data) {
  map.getSource(id)?.setData(data)
}

// Shared interactive spatial-analysis panel: measure distance, buffer-radius
// feature count, and nearest-feature lookup. Purely additive: only intercepts
// map clicks while a mode is active, so it never touches the existing
// assets-dot/muni-fill/clusters click-to-select handlers wired in AssetMap.
export function useSpatialTools({ mapRef, mapReady, targets }) {
  const targetKeys = Object.keys(targets)
  const [mode, setMode] = useState('off')
  const [targetKey, setTargetKey] = useState(targetKeys[0] ?? '')
  const [measurePoints, setMeasurePoints] = useState([])
  const [bufferRadiusKm, setBufferRadiusKm] = useState(5)
  const [bufferCount, setBufferCount] = useState(null)
  const [nearestResult, setNearestResult] = useState(null)

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    function setup() {
      ensureLineSource(map, MEASURE_SOURCE, '#facc15')
      ensureFillSource(map, BUFFER_SOURCE, '#38bdf8')
      ensureLineSource(map, NEAREST_SOURCE, '#f472b6')
    }
    if (map.isStyleLoaded()) setup()
    else map.once('styledata', setup)
  }, [mapRef, mapReady])

  const clearAll = () => {
    setMeasurePoints([])
    setBufferCount(null)
    setNearestResult(null)
    const map = mapRef.current
    if (!map) return
    setSourceData(map, MEASURE_SOURCE, { type: 'FeatureCollection', features: [] })
    setSourceData(map, BUFFER_SOURCE, { type: 'FeatureCollection', features: [] })
    setSourceData(map, NEAREST_SOURCE, { type: 'FeatureCollection', features: [] })
  }

  const setModeAndReset = (next) => {
    clearAll()
    setMode(next)
  }

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    function onClick(e) {
      if (mode === 'off') return
      const lngLat = [e.lngLat.lng, e.lngLat.lat]

      if (mode === 'measure') {
        setMeasurePoints((prev) => {
          const next = [...prev, lngLat]
          if (next.length >= 2) {
            setSourceData(map, MEASURE_SOURCE, featureCollection([
              { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: next } },
            ]))
          }
          return next
        })
        return
      }

      if (mode === 'buffer') {
        const poly = turfCircle(point(lngLat), bufferRadiusKm, { steps: 64, units: 'kilometers' })
        setSourceData(map, BUFFER_SOURCE, featureCollection([poly]))
        const getFeatures = targets[targetKey]
        const inside = getFeatures ? getFeatures().filter((f) => booleanPointInPolygon(f, poly)).length : 0
        setBufferCount(inside)
        return
      }

      if (mode === 'nearest') {
        const getFeatures = targets[targetKey]
        const candidates = getFeatures ? getFeatures() : []
        if (candidates.length === 0) {
          setNearestResult(null)
          return
        }
        const origin = point(lngLat)
        const fc = { type: 'FeatureCollection', features: candidates }
        const nearest = turfNearestPoint(origin, fc)
        const distanceKm = turfDistance(origin, nearest, { units: 'kilometers' })
        const connector = {
          type: 'Feature', properties: {},
          geometry: { type: 'LineString', coordinates: [lngLat, nearest.geometry.coordinates] },
        }
        setSourceData(map, NEAREST_SOURCE, { type: 'FeatureCollection', features: [connector, nearest] })
        setNearestResult({ distanceKm, properties: nearest.properties ?? {} })
      }
    }

    map.on('click', onClick)
    return () => map.off('click', onClick)
  }, [mapRef, mapReady, mode, targetKey, bufferRadiusKm, targets])

  const measureLengthKm = measurePoints.length >= 2
    ? turfLength({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: measurePoints } }, { units: 'kilometers' })
    : 0

  return {
    mode, setMode: setModeAndReset, targetKey, setTargetKey, targetKeys,
    measurePoints, measureLengthKm, bufferRadiusKm, setBufferRadiusKm,
    bufferCount, nearestResult, clearAll,
  }
}

export function SpatialToolsPanel(state) {
  const {
    mode, setMode, targetKey, setTargetKey, targetKeys, measureLengthKm,
    measurePoints, bufferRadiusKm, setBufferRadiusKm, bufferCount, nearestResult, clearAll,
  } = state

  return (
    <div className="absolute right-3 top-16 w-[260px] rounded-xl border border-slate-700/70 bg-slate-950/85 p-3 shadow-xl backdrop-blur text-[11px]">
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Spatial tools</span>
        {mode !== 'off' && (
          <button type="button" onClick={clearAll} className="ml-auto text-[10px] text-slate-500 underline hover:text-slate-300">
            Clear
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {['off', 'measure', 'buffer', 'nearest'].map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            aria-pressed={mode === m}
            className={`rounded border px-2 py-1 text-[11px] transition ${
              mode === m ? 'border-sky-500/40 bg-sky-500/10 text-sky-300' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'
            }`}
          >
            {m === 'off' ? 'Off' : m[0].toUpperCase() + m.slice(1)}
          </button>
        ))}
      </div>
      {mode !== 'off' && targetKeys.length > 0 && (
        <select
          value={targetKey}
          onChange={(e) => setTargetKey(e.target.value)}
          className="mt-1.5 w-full rounded border border-slate-800 bg-slate-950/70 px-1.5 py-1 text-[11px] text-slate-300"
        >
          {targetKeys.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      )}
      {mode === 'measure' && (
        <p className="mt-1.5 text-slate-400">
          Click to add vertices.
          {measurePoints.length >= 2 && (
            <> <strong className="text-slate-200">{measureLengthKm.toFixed(2)} km</strong> · {(measureLengthKm * 0.621371).toFixed(2)} mi</>
          )}
        </p>
      )}
      {mode === 'buffer' && (
        <div className="mt-1.5 text-slate-400">
          <p>Click to set center. Radius:</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {BUFFER_RADII_KM.map((r) => (
              <button
                key={r} type="button" onClick={() => setBufferRadiusKm(r)} aria-pressed={bufferRadiusKm === r}
                className={`rounded border px-1.5 py-0.5 text-[10px] ${bufferRadiusKm === r ? 'border-sky-500/40 bg-sky-500/10 text-sky-300' : 'border-slate-800 text-slate-500'}`}
              >
                {r} km
              </button>
            ))}
          </div>
          {bufferCount !== null && <p className="mt-1 text-slate-200">{bufferCount} feature{bufferCount === 1 ? '' : 's'} within {bufferRadiusKm} km</p>}
        </div>
      )}
      {mode === 'nearest' && (
        <p className="mt-1.5 text-slate-400">
          Click to query the nearest feature.
          {nearestResult && <> <strong className="text-slate-200">{nearestResult.distanceKm.toFixed(2)} km</strong> away</>}
        </p>
      )}
    </div>
  )
}
