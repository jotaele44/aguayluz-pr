import { useEffect, useState } from 'react'
import { featureCollection, point } from '@turf/helpers'
import turfLength from '@turf/length'
import turfDistance from '@turf/distance'
import turfCircle from '@turf/circle'
import booleanPointInPolygon from '@turf/boolean-point-in-polygon'
import turfNearestPoint from '@turf/nearest-point'
import { drawPolygonCollection, formatArea, polygonFromVertices, ringAreaM2 } from '../lib/gis/measure'
import { googleMapsPointUrl, googleStreetViewUrl } from '../lib/gis/externalLinks'
import { downloadBlob } from '../lib/gis/printMap'
import { PROXY_LABEL, evidenceText, linesForEdges } from '../lib/gis/networkApi'

const MEASURE_SOURCE = 'tool-measure-line'
const BUFFER_SOURCE = 'tool-buffer-circle'
const NEAREST_SOURCE = 'tool-nearest-highlight'
const DRAW_SOURCE = 'tool-draw-polygon'
const NETWORK_SOURCE = 'tool-network-links'
const CLIENT_MODES = ['off', 'measure', 'area', 'buffer', 'nearest']
const SERVER_MODES = ['identify', 'query', 'trace', 'scenario']
const ASSET_LAYERS = ['power_assets', 'water_assets', 'wastewater_assets']
const MODE_LABEL = {
  off: 'Off', measure: 'Measure', area: 'Area', buffer: 'Buffer', nearest: 'Nearest',
  identify: 'Identify', query: 'Polygon query', trace: 'Dependencies', scenario: 'Scenario',
}
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

function errorText(error) {
  return error instanceof Error ? error.message : String(error)
}

/**
 * `gis` (optional) wires the backend /gis/* tools: `client` (lib/gis/gisApi),
 * `network` (lib/gis/networkApi), `activeLayers()` -> catalog layer ids switched on,
 * and `exportable(layerId)`. Without it only the client-side tools are offered.
 */
export function useSpatialTools({ mapRef, mapReady, targets, interactionLockRef, gis }) {
  const targetKeys = Object.keys(targets)
  const [mode, setMode] = useState('off')
  const [targetKey, setTargetKey] = useState(targetKeys[0] ?? '')
  const [measurePoints, setMeasurePoints] = useState([])
  const [bufferRadiusKm, setBufferRadiusKm] = useState(5)
  const [bufferOrigin, setBufferOrigin] = useState(null)
  const [bufferResult, setBufferResult] = useState(null)
  const [nearestOrigin, setNearestOrigin] = useState(null)
  const [nearestResult, setNearestResult] = useState(null)
  const [drawVertices, setDrawVertices] = useState([])
  const [identifyState, setIdentifyState] = useState({ status: 'idle' })
  const [queryState, setQueryState] = useState({ status: 'idle' })
  const [exportError, setExportError] = useState(null)
  const [traceDirection, setTraceDirection] = useState('downstream')
  const [traceState, setTraceState] = useState({ status: 'idle' })
  const [scenarioSelection, setScenarioSelection] = useState([])
  const [scenarioState, setScenarioState] = useState({ status: 'idle' })

  interactionLockRef.current = mode !== 'off'

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    function setup() {
      ensureLineSource(map, MEASURE_SOURCE, '#facc15')
      ensureFillSource(map, BUFFER_SOURCE, '#38bdf8')
      ensureLineSource(map, NEAREST_SOURCE, '#f472b6')
      ensureFillSource(map, DRAW_SOURCE, '#a3e635')
      ensureLineSource(map, NETWORK_SOURCE, '#fb923c')
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
    setDrawVertices([])
    setIdentifyState({ status: 'idle' })
    setQueryState({ status: 'idle' })
    setExportError(null)
    setTraceState({ status: 'idle' })
    setScenarioSelection([])
    setScenarioState({ status: 'idle' })
    const map = mapRef.current
    if (!map) return
    setSourceData(map, MEASURE_SOURCE, EMPTY_COLLECTION)
    setSourceData(map, BUFFER_SOURCE, EMPTY_COLLECTION)
    setSourceData(map, NEAREST_SOURCE, EMPTY_COLLECTION)
    setSourceData(map, DRAW_SOURCE, EMPTY_COLLECTION)
    setSourceData(map, NETWORK_SOURCE, EMPTY_COLLECTION)
  }

  const highlightEdges = async (edgeIds) => {
    if (!gis?.network) return
    try {
      const lines = await gis.network.dependencyLines()
      setSourceData(mapRef.current, NETWORK_SOURCE, linesForEdges(lines, edgeIds))
    } catch { /* highlighting is best-effort; the readout already lists every link */ }
  }

  // The asset under a click, resolved server-side so clustered or hidden map
  // symbols do not matter. Returns null when no asset is within 75 m.
  const assetAt = async (lngLat) => {
    const hit = await gis.client.identify(lngLat[0], lngLat[1], ASSET_LAYERS, 75)
    return hit.hits[0] ?? null
  }

  const runIdentify = (lngLat) => {
    setIdentifyState({ status: 'loading' })
    gis.client.identify(lngLat[0], lngLat[1], gis.activeLayers())
      .then((data) => setIdentifyState({ status: 'ready', data }))
      .catch((error) => setIdentifyState({ status: 'error', message: errorText(error) }))
  }

  const runTraceAt = async (lngLat, direction) => {
    setTraceState({ status: 'loading' })
    try {
      const asset = await assetAt(lngLat)
      if (!asset) {
        setTraceState({ status: 'error', message: 'No asset within 75 m of the click.' })
        return
      }
      const data = await gis.network.trace(asset.feature_id, direction)
      setTraceState({ status: 'ready', data, asset })
      await highlightEdges(data.hits.map((hit) => hit.edge_id))
    } catch (error) {
      setTraceState({ status: 'error', message: errorText(error) })
    }
  }

  const toggleScenarioAssetAt = async (lngLat) => {
    try {
      const asset = await assetAt(lngLat)
      if (!asset) return
      setScenarioState({ status: 'idle' })
      setScenarioSelection((current) => (
        current.some((item) => item.feature_id === asset.feature_id)
          ? current.filter((item) => item.feature_id !== asset.feature_id)
          : [...current, { layer_id: asset.layer_id, feature_id: asset.feature_id, label: asset.properties?.asset_name ?? asset.feature_id }]
      ))
    } catch (error) {
      setScenarioState({ status: 'error', message: errorText(error) })
    }
  }

  const runScenario = async () => {
    if (!gis?.network || scenarioSelection.length === 0) return
    setScenarioState({ status: 'loading' })
    try {
      const data = await gis.network.scenario(scenarioSelection.map(({ layer_id, feature_id }) => ({ layer_id, feature_id })))
      setScenarioState({ status: 'ready', data })
      await highlightEdges(data.impacted.map((item) => item.edge_id).filter(Boolean))
    } catch (error) {
      setScenarioState({ status: 'error', message: errorText(error) })
    }
  }

  const runPolygonQuery = () => {
    const polygon = polygonFromVertices(drawVertices)
    if (!gis || !polygon) return
    const layers = gis.activeLayers()
    if (layers.length === 0) {
      setQueryState({ status: 'error', message: 'Switch on at least one layer to query.' })
      return
    }
    setQueryState({ status: 'loading' })
    setExportError(null)
    gis.client.queryPolygon(polygon, layers)
      .then((data) => setQueryState({ status: 'ready', data }))
      .catch((error) => setQueryState({ status: 'error', message: errorText(error) }))
  }

  const exportPolygonQuery = (format) => {
    const polygon = polygonFromVertices(drawVertices)
    if (!gis || !polygon || queryState.status !== 'ready') return
    const layers = queryState.data.layers.map((layer) => layer.layer_id).filter((layerId) => gis.exportable(layerId))
    if (layers.length === 0) {
      setExportError('None of the queried layers is exportable (only PUBLIC layers are).')
      return
    }
    setExportError(null)
    gis.client.exportPolygon(polygon, layers, format)
      .then((blob) => downloadBlob(blob, `aguayluz-gis-export.${format === 'csv' ? 'csv' : 'geojson'}`))
      .catch((error) => setExportError(errorText(error)))
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

      if (mode === 'area' || mode === 'query') {
        setDrawVertices((previous) => {
          const next = [...previous, lngLat]
          setSourceData(map, DRAW_SOURCE, drawPolygonCollection(next))
          return next
        })
        if (mode === 'query') setQueryState({ status: 'idle' })
        return
      }
      if (mode === 'identify') {
        runIdentify(lngLat)
        return
      }
      if (mode === 'trace') {
        runTraceAt(lngLat, traceDirection)
        return
      }
      if (mode === 'scenario') {
        toggleScenarioAssetAt(lngLat)
        return
      }

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
  }, [mapRef, mapReady, mode, traceDirection, gis])

  const measureLengthKm = measurePoints.length >= 2
    ? turfLength({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: measurePoints } }, { units: 'kilometers' })
    : 0

  const drawAreaM2 = drawVertices.length >= 3 ? ringAreaM2(drawVertices) : 0

  return {
    mode, setMode: setModeAndReset, targetKey, setTargetKey, targetKeys,
    measurePoints, measureLengthKm, bufferRadiusKm, setBufferRadiusKm,
    bufferResult, nearestResult, clearAll,
    gisEnabled: Boolean(gis), exportable: gis?.exportable ?? (() => false),
    drawVertices, drawAreaM2, identifyState, queryState, exportError, runPolygonQuery, exportPolygonQuery,
    traceDirection, setTraceDirection, traceState, scenarioSelection, scenarioState, runScenario,
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

function formatValue(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function locationText(value) {
  if (!value) return '—'
  return `${formatValue(value.name)} (${formatValue(value.id)})`
}

function IdentifyReadout({ state }) {
  if (state.status === 'idle') return <p className="mt-1.5 text-slate-400">Click the map to identify features in the active layers.</p>
  if (state.status === 'loading') return <p className="mt-1.5 text-slate-400">Identifying…</p>
  if (state.status === 'error') return <p role="alert" className="mt-1.5 text-red-300">Identify failed: {state.message}</p>
  const { point: clicked, hits, location } = state.data
  return (
    <div className="mt-1.5 space-y-1 text-slate-400">
      <p>
        {clicked.lat.toFixed(6)}, {clicked.lon.toFixed(6)} ·{' '}
        <a className="underline" href={googleMapsPointUrl(clicked.lon, clicked.lat)} target="_blank" rel="noreferrer noopener">Google Maps</a> ·{' '}
        <a className="underline" href={googleStreetViewUrl(clicked.lon, clicked.lat)} target="_blank" rel="noreferrer noopener">Street View</a>
      </p>
      <p>Municipio: {locationText(location.municipio)} · Barrio: {locationText(location.barrio)}</p>
      {hits.length === 0 && <p>No features within {state.data.tolerance_m} m.</p>}
      {hits.map((hit, index) => (
        <details key={`${hit.layer_id}-${hit.feature_id ?? index}`} open={index === 0}>
          <summary>{hit.layer_id} · {hit.feature_id ?? 'unidentified'} · {hit.distance_m} m</summary>
          <dl>
            {Object.entries(hit.properties).map(([key, value]) => (
              <div key={key}><dt className="inline text-slate-500">{key}: </dt><dd className="inline text-slate-200">{formatValue(value)}</dd></div>
            ))}
          </dl>
        </details>
      ))}
      <p className="text-[10px] text-slate-500">Spatial relation only · evidence {state.data.evidence_state} · identity effect NONE</p>
    </div>
  )
}

function QueryReadout({ state, exportable, onExport, exportError }) {
  if (state.status === 'idle') return null
  if (state.status === 'loading') return <p className="mt-1 text-slate-400">Querying…</p>
  if (state.status === 'error') return <p role="alert" className="mt-1 text-red-300">Query failed: {state.message}</p>
  const anyExportable = state.data.layers.some((layer) => exportable(layer.layer_id))
  return (
    <div className="mt-1 space-y-0.5 text-slate-400">
      <p><strong className="text-slate-200">{state.data.total_matched}</strong> feature{state.data.total_matched === 1 ? '' : 's'} in the polygon</p>
      {state.data.layers.map((layer) => (
        <p key={layer.layer_id}>
          {layer.layer_id}: {layer.matched_count}{layer.truncated ? ` (first ${layer.returned_count} returned)` : ''}
          {layer.excluded_count > 0 ? ` · ${layer.excluded_count} without usable geometry` : ''}
          {layer.error ? ` · ${layer.error}` : ''}
          {exportable(layer.layer_id) ? '' : ' · not exportable'}
        </p>
      ))}
      <p className="text-[10px] text-slate-500">Evidence {state.data.evidence_state} · identity effect NONE</p>
      {anyExportable && (
        <div className="flex gap-1">
          <button type="button" className="rounded border border-slate-800 px-1.5 py-0.5" onClick={() => onExport('geojson')}>Export GeoJSON</button>
          <button type="button" className="rounded border border-slate-800 px-1.5 py-0.5" onClick={() => onExport('csv')}>Export CSV</button>
        </div>
      )}
      {exportError && <p role="alert" className="text-red-300">Export failed: {exportError}</p>}
    </div>
  )
}

function ProxyWarning({ show }) {
  if (!show) return null
  return (
    <p role="note" className="rounded border border-amber-500/40 p-1 text-amber-300">
      {PROXY_LABEL}: at least one link used here was inferred from distance and still needs evidence.
    </p>
  )
}

function TraceReadout({ state }) {
  if (state.status === 'idle') return <p className="mt-1 text-slate-400">Click an asset to trace its recorded dependencies.</p>
  if (state.status === 'loading') return <p className="mt-1 text-slate-400">Tracing…</p>
  if (state.status === 'error') return <p role="alert" className="mt-1 text-red-300">Trace failed: {state.message}</p>
  const { data, asset } = state
  return (
    <div className="mt-1 space-y-0.5 text-slate-400">
      <p>From <strong className="text-slate-200">{asset.properties?.asset_name ?? asset.feature_id}</strong> ({data.direction}): {data.hits.length} linked feature{data.hits.length === 1 ? '' : 's'}</p>
      <ProxyWarning show={data.unverified_links_used} />
      {data.hits.map((hit) => (
        <p key={hit.feature_id}>{hit.hops}× {hit.layer_id ?? hit.node_type ?? 'node'} · {hit.feature_id} — {evidenceText(hit)}</p>
      ))}
      <p className="text-[10px] text-slate-500">Recorded links only · evidence {data.evidence_state}</p>
    </div>
  )
}

function ScenarioReadout({ selection, state, onRun }) {
  return (
    <div className="mt-1 space-y-0.5 text-slate-400">
      <p>Click assets to mark them out of service ({selection.length} selected), then run.</p>
      {selection.map((item) => <p key={item.feature_id}>✕ {item.label} ({item.layer_id})</p>)}
      <button type="button" className="rounded border border-slate-800 px-1.5 py-0.5" disabled={selection.length === 0 || state.status === 'loading'} onClick={onRun}>
        Run scenario
      </button>
      {state.status === 'loading' && <p>Running…</p>}
      {state.status === 'error' && <p role="alert" className="text-red-300">Scenario failed: {state.message}</p>}
      {state.status === 'ready' && (
        <>
          <p className="font-semibold text-slate-200">HYPOTHESIS · not persisted</p>
          <ProxyWarning show={state.data.unverified_links_used} />
          <p>{state.data.impacted.length} dependent feature{state.data.impacted.length === 1 ? '' : 's'} would lose service:</p>
          {state.data.impacted.map((item) => (
            <p key={item.feature_id}>{item.hops}× {item.layer_id ?? 'node'} · {item.feature_id} — {evidenceText(item)}</p>
          ))}
          <p>Affected areas: {state.data.affected_areas.length ? state.data.affected_areas.map((a) => a.name ?? a.area_id).join(', ') : 'none resolved'}</p>
          {state.data.notes.map((note) => <p key={note} className="text-[10px] text-slate-500">{note}</p>)}
        </>
      )}
    </div>
  )
}

export function SpatialToolsPanel(state) {
  const {
    mode, setMode, targetKey, setTargetKey, targetKeys, measureLengthKm,
    measurePoints, bufferRadiusKm, setBufferRadiusKm, bufferResult, nearestResult, clearAll,
    gisEnabled, exportable, drawVertices, drawAreaM2, identifyState, queryState, exportError,
    runPolygonQuery, exportPolygonQuery, traceDirection, setTraceDirection, traceState,
    scenarioSelection, scenarioState, runScenario,
  } = state
  const modes = gisEnabled ? [...CLIENT_MODES, ...SERVER_MODES] : CLIENT_MODES

  return (
    <div className="w-full rounded-xl border border-slate-700/70 bg-slate-950/85 p-3 shadow-xl backdrop-blur text-[11px]">
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Spatial tools</span>
        {mode !== 'off' && (
          <button type="button" onClick={clearAll} className="ml-auto text-[10px] text-slate-500 underline hover:text-slate-300">
            Clear
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {modes.map((candidateMode) => (
          <button
            key={candidateMode}
            type="button"
            onClick={() => setMode(candidateMode)}
            aria-pressed={mode === candidateMode}
            className={`rounded border px-2 py-1 text-[11px] transition ${
              mode === candidateMode ? 'border-sky-500/40 bg-sky-500/10 text-sky-300' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'
            }`}
          >
            {MODE_LABEL[candidateMode]}
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
      {mode === 'area' && (
        <p className="mt-1.5 text-slate-400">
          Click to add polygon vertices.
          {drawVertices.length >= 3 && <> <strong className="text-slate-200">{formatArea(drawAreaM2)}</strong></>}
        </p>
      )}
      {mode === 'identify' && <IdentifyReadout state={identifyState} />}
      {mode === 'query' && (
        <div className="mt-1.5 text-slate-400">
          <p>Click to add polygon vertices, then query the active layers.{drawVertices.length >= 3 && <> {formatArea(drawAreaM2)}</>}</p>
          <button type="button" className="mt-1 rounded border border-slate-800 px-1.5 py-0.5" disabled={drawVertices.length < 3 || queryState.status === 'loading'} onClick={runPolygonQuery}>
            Run query
          </button>
          <QueryReadout state={queryState} exportable={exportable} onExport={exportPolygonQuery} exportError={exportError} />
        </div>
      )}
      {mode === 'trace' && (
        <div className="mt-1.5 text-slate-400">
          <div className="flex gap-1">
            {['upstream', 'downstream'].map((direction) => (
              <button
                key={direction} type="button" onClick={() => setTraceDirection(direction)} aria-pressed={traceDirection === direction}
                className={`rounded border px-1.5 py-0.5 text-[10px] ${traceDirection === direction ? 'border-sky-500/40 bg-sky-500/10 text-sky-300' : 'border-slate-800 text-slate-500'}`}
              >
                {direction === 'upstream' ? 'What it depends on' : 'What depends on it'}
              </button>
            ))}
          </div>
          <TraceReadout state={traceState} />
        </div>
      )}
      {mode === 'scenario' && <ScenarioReadout selection={scenarioSelection} state={scenarioState} onRun={runScenario} />}
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
