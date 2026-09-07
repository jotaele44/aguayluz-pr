import { useEffect, useState } from 'react'
import { featureCollection, point } from '@turf/helpers'
import turfLength from '@turf/length'
import turfDistance from '@turf/distance'
import turfCircle from '@turf/circle'
import booleanPointInPolygon from '@turf/boolean-point-in-polygon'
import turfNearestPoint from '@turf/nearest-point'

const MEASURE_SOURCE = 'tool-measure-line'
const BUFFER_SOURCE = 'tool-buffer-circle'
const NEAREST_SOURCE = 'tool-nearest-highlight'
const BUFFER_RADII_KM = [1, 5, 10, 25]
const EMPTY_COLLECTION = { type: 'FeatureCollection', features: [] }

function finitePosition(coordinates) {
  return Array.isArray(coordinates)
    && coordinates.length >= 2
    && Number.isFinite(coordinates[0])
    && Number.isFinite(coordinates[1])
}

export function pointCandidateSet(features = []) {
  const points = []
  let excludedCount = 0
  for (const candidate of Array.isArray(features) ? features : []) {
    if (candidate?.type === 'Feature'
      && candidate.geometry?.type === 'Point'
      && finitePosition(candidate.geometry.coordinates)) {
      points.push(candidate)
    } else {
      excludedCount += 1
    }
  }
  return { features: points, excludedCount }
}

export function measureFeatureCollection(coordinates = []) {
  const validCoordinates = coordinates.filter(finitePosition)
  const features = validCoordinates.map((coordinates) => point(coordinates))
  if (validCoordinates.length >= 2) {
    features.unshift({
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: validCoordinates },
    })
  }
  return featureCollection(features)
}

export function bufferPointCandidates(origin, radiusKm, candidates = []) {
  if (!finitePosition(origin) || !Number.isFinite(radiusKm) || radiusKm <= 0) return null
  const candidateSet = pointCandidateSet(candidates)
  const polygon = turfCircle(point(origin), radiusKm, { steps: 64, units: 'kilometers' })
  const matches = candidateSet.features.filter((candidate) => booleanPointInPolygon(candidate, polygon))
  return { polygon, matches, ...candidateSet }
}

export function nearestPointCandidate(origin, candidates = []) {
  if (!finitePosition(origin)) return null
  const candidateSet = pointCandidateSet(candidates)
  if (candidateSet.features.length === 0) return { nearest: null, distanceKm: null, ...candidateSet }
  const queryPoint = point(origin)
  const nearest = turfNearestPoint(queryPoint, featureCollection(candidateSet.features))
  return {
    nearest,
    distanceKm: turfDistance(queryPoint, nearest, { units: 'kilometers' }),
    ...candidateSet,
  }
}

function ensureLineSource(map, id, color) {
  if (!map.getSource(id)) {
    map.addSource(id, { type: 'geojson', data: EMPTY_COLLECTION })
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
    map.addSource(id, { type: 'geojson', data: EMPTY_COLLECTION })
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
  map?.getSource(id)?.setData(data)
}

function readTarget(targets, targetKey) {
  try {
    const value = targets[targetKey]?.()
    return { candidates: Array.isArray(value) ? value : [], sourceError: null }
  } catch (error) {
    return { candidates: [], sourceError: error instanceof Error ? error.message : String(error) }
  }
}

function candidateLabel(properties = {}) {
  return properties.asset_id
    ?? properties.event_id
    ?? properties.alert_id
    ?? properties.id
    ?? 'unnamed candidate'
}

export function useSpatialTools({ mapRef, mapReady, targets, interactionLockRef }) {
  const targetKeys = Object.keys(targets)
  const [mode, setMode] = useState('off')
  const [targetKey, setTargetKey] = useState(targetKeys[0] ?? '')
  const [measurePoints, setMeasurePoints] = useState([])
  const [bufferRadiusKm, setBufferRadiusKm] = useState(5)
  const [bufferOrigin, setBufferOrigin] = useState(null)
  const [bufferResult, setBufferResult] = useState(null)
  const [nearestOrigin, setNearestOrigin] = useState(null)
  const [nearestResult, setNearestResult] = useState(null)

  interactionLockRef.current = mode !== 'off'

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
    setBufferOrigin(null)
    setBufferResult(null)
    setNearestOrigin(null)
    setNearestResult(null)
    const map = mapRef.current
    if (!map) return
    setSourceData(map, MEASURE_SOURCE, EMPTY_COLLECTION)
    setSourceData(map, BUFFER_SOURCE, EMPTY_COLLECTION)
    setSourceData(map, NEAREST_SOURCE, EMPTY_COLLECTION)
  }

  const setModeAndReset = (next) => {
    clearAll()
    setMode(next)
  }

  useEffect(() => {
    if (mode !== 'buffer' || !bufferOrigin) return
    const map = mapRef.current
    const { candidates, sourceError } = readTarget(targets, targetKey)
    const analysis = bufferPointCandidates(bufferOrigin, bufferRadiusKm, candidates)
    if (!analysis) {
      setBufferResult(null)
      setSourceData(map, BUFFER_SOURCE, EMPTY_COLLECTION)
      return
    }
    setSourceData(map, BUFFER_SOURCE, featureCollection([analysis.polygon]))
    setBufferResult({
      count: analysis.matches.length,
      candidateCount: analysis.features.length,
      excludedCount: analysis.excludedCount,
      identityEffect: 'NONE',
      origin: bufferOrigin,
      radiusKm: bufferRadiusKm,
      sourceError,
      state: sourceError ? 'FAIL' : 'PASS',
      targetKey,
    })
  }, [bufferOrigin, bufferRadiusKm, mapRef, mode, targetKey, targets])

  useEffect(() => {
    if (mode !== 'nearest' || !nearestOrigin) return
    const map = mapRef.current
    const { candidates, sourceError } = readTarget(targets, targetKey)
    const analysis = nearestPointCandidate(nearestOrigin, candidates)
    if (!analysis || !analysis.nearest) {
      setSourceData(map, NEAREST_SOURCE, EMPTY_COLLECTION)
      setNearestResult({
        candidateCount: analysis?.features.length ?? 0,
        excludedCount: analysis?.excludedCount ?? 0,
        identityEffect: 'NONE',
        origin: nearestOrigin,
        sourceError,
        state: sourceError ? 'FAIL' : 'UNRESOLVED',
        targetKey,
      })
      return
    }
    const connector = {
      type: 'Feature', properties: {},
      geometry: { type: 'LineString', coordinates: [nearestOrigin, analysis.nearest.geometry.coordinates] },
    }
    setSourceData(map, NEAREST_SOURCE, featureCollection([connector, analysis.nearest]))
    setNearestResult({
      candidateCount: analysis.features.length,
      candidateLabel: candidateLabel(analysis.nearest.properties),
      distanceKm: analysis.distanceKm,
      excludedCount: analysis.excludedCount,
      identityEffect: 'NONE',
      origin: nearestOrigin,
      properties: analysis.nearest.properties ?? {},
      sourceError,
      state: sourceError ? 'FAIL' : 'CANDIDATE_NOT_IDENTITY',
      targetKey,
    })
  }, [mapRef, mode, nearestOrigin, targetKey, targets])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    function onClick(event) {
      if (mode === 'off') return
      const lngLat = [event.lngLat.lng, event.lngLat.lat]
      if (!finitePosition(lngLat)) return

      if (mode === 'measure') {
        setMeasurePoints((previous) => {
          const next = [...previous, lngLat]
          setSourceData(map, MEASURE_SOURCE, measureFeatureCollection(next))
          return next
        })
        return
      }

      if (mode === 'buffer') {
        setBufferOrigin(lngLat)
        return
      }

      if (mode === 'nearest') setNearestOrigin(lngLat)
    }

    map.on('click', onClick)
    return () => map.off('click', onClick)
  }, [mapRef, mapReady, mode])

  const measureLengthKm = measurePoints.length >= 2
    ? turfLength({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: measurePoints } }, { units: 'kilometers' })
    : 0

  return {
    mode, setMode: setModeAndReset, targetKey, setTargetKey, targetKeys,
    measurePoints, measureLengthKm, bufferRadiusKm, setBufferRadiusKm,
    bufferResult, nearestResult, clearAll,
  }
}

function QueryEvidence({ result }) {
  if (!result) return null
  return (
    <div className="mt-1 rounded border border-slate-800 bg-slate-950/60 p-1.5 text-[10px] leading-relaxed text-slate-500">
      <div>Target: <span className="text-slate-300">{result.targetKey}</span> · valid candidates {result.candidateCount} · excluded malformed {result.excludedCount}</div>
      <div>Query: {result.origin.map((value) => value.toFixed(5)).join(', ')}</div>
      <div>Evidence: discovery only · identity effect <span className="text-amber-300">{result.identityEffect}</span> · state <span className="text-slate-300">{result.state}</span></div>
      {result.sourceError && <div className="text-red-300">Target error: {result.sourceError}</div>}
    </div>
  )
}

export function SpatialToolsPanel(state) {
  const {
    mode, setMode, targetKey, setTargetKey, targetKeys, measureLengthKm,
    measurePoints, bufferRadiusKm, setBufferRadiusKm, bufferResult, nearestResult, clearAll,
  } = state

  return (
    <div className="absolute right-3 top-16 w-[280px] rounded-xl border border-slate-700/70 bg-slate-950/85 p-3 shadow-xl backdrop-blur text-[11px]">
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Spatial tools</span>
        {mode !== 'off' && (
          <button type="button" onClick={clearAll} className="ml-auto text-[10px] text-slate-500 underline hover:text-slate-300">
            Clear
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {['off', 'measure', 'buffer', 'nearest'].map((candidateMode) => (
          <button
            key={candidateMode}
            type="button"
            onClick={() => setMode(candidateMode)}
            aria-pressed={mode === candidateMode}
            className={`rounded border px-2 py-1 text-[11px] transition ${
              mode === candidateMode ? 'border-sky-500/40 bg-sky-500/10 text-sky-300' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'
            }`}
          >
            {candidateMode === 'off' ? 'Off' : candidateMode[0].toUpperCase() + candidateMode.slice(1)}
          </button>
        ))}
      </div>
      {['buffer', 'nearest'].includes(mode) && targetKeys.length > 0 && (
        <select
          aria-label="Spatial target layer"
          value={targetKey}
          onChange={(event) => setTargetKey(event.target.value)}
          className="mt-1.5 w-full rounded border border-slate-800 bg-slate-950/70 px-1.5 py-1 text-[11px] text-slate-300"
        >
          {targetKeys.map((key) => <option key={key} value={key}>{key}</option>)}
        </select>
      )}
      {mode === 'measure' && (
        <p className="mt-1.5 text-slate-400">
          Click to add visible vertices.
          {measurePoints.length >= 2 && (
            <> <strong className="text-slate-200">{measureLengthKm.toFixed(2)} km</strong> · {(measureLengthKm * 0.621371).toFixed(2)} mi</>
          )}
        </p>
      )}
      {mode === 'buffer' && (
        <div className="mt-1.5 text-slate-400">
          <p>Click to set center. Radius:</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {BUFFER_RADII_KM.map((radiusKm) => (
              <button
                key={radiusKm} type="button" onClick={() => setBufferRadiusKm(radiusKm)} aria-pressed={bufferRadiusKm === radiusKm}
                className={`rounded border px-1.5 py-0.5 text-[10px] ${bufferRadiusKm === radiusKm ? 'border-sky-500/40 bg-sky-500/10 text-sky-300' : 'border-slate-800 text-slate-500'}`}
              >
                {radiusKm} km
              </button>
            ))}
          </div>
          {bufferResult && <p className="mt-1 text-slate-200">{bufferResult.count} feature{bufferResult.count === 1 ? '' : 's'} within {bufferResult.radiusKm} km</p>}
          <QueryEvidence result={bufferResult} />
        </div>
      )}
      {mode === 'nearest' && (
        <div className="mt-1.5 text-slate-400">
          <p>Click to query the nearest feature.</p>
          {nearestResult?.distanceKm != null && (
            <p><strong className="text-slate-200">{nearestResult.candidateLabel}</strong> · {nearestResult.distanceKm.toFixed(2)} km away</p>
          )}
          {nearestResult?.state === 'UNRESOLVED' && <p className="text-amber-300">No valid point candidate is available.</p>}
          <QueryEvidence result={nearestResult} />
        </div>
      )}
    </div>
  )
}
