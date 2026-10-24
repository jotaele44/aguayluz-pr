import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ExternalLink, MapPinned } from 'lucide-react'

const WIDTH = 920
const HEIGHT = 330
const PAD = 18

const METRICS = {
  assets: { label: 'Assets', key: 'asset_count' },
  active: { label: 'Active assets', key: 'active_asset_count' },
  events: { label: 'Events', key: 'event_count' },
  outages: { label: 'Active outages', key: 'active_outage_count' },
}

function coordinatePairs(geometry) {
  const pairs = []
  const walk = (value) => {
    if (!Array.isArray(value)) return
    if (value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') {
      pairs.push(value)
      return
    }
    value.forEach(walk)
  }
  walk(geometry?.coordinates)
  return pairs
}

function geometryPath(geometry, project) {
  if (!geometry || !['Polygon', 'MultiPolygon'].includes(geometry.type)) return ''
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  return polygons.map((polygon) =>
    polygon.map((ring) => {
      if (!Array.isArray(ring) || ring.length === 0) return ''
      return ring.map((coord, index) => {
        const [x, y] = project(coord)
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
      }).join(' ') + ' Z'
    }).join(' ')
  ).join(' ')
}

function bucketClass(value, max) {
  if (!value || max <= 0) return 'fill-slate-800'
  const ratio = value / max
  if (ratio >= 0.75) return 'fill-sky-400/80'
  if (ratio >= 0.5) return 'fill-sky-500/65'
  if (ratio >= 0.25) return 'fill-sky-700/70'
  return 'fill-sky-900/70'
}

export default function MunicipalOverviewMap({
  geojson,
  summary,
  metric = 'assets',
  onMetricChange,
  selectedGeoid,
  onSelect,
  detail,
  detailLoading = false,
}) {
  const features = geojson?.features ?? []
  const rows = summary?.items ?? []
  const rowsByGeoid = useMemo(
    () => new Map(rows.map((row) => [String(row.geoid), row])),
    [rows],
  )
  const metricMeta = METRICS[metric] ?? METRICS.assets
  const maxValue = Math.max(0, ...rows.map((row) => Number(row[metricMeta.key]) || 0))

  const projection = useMemo(() => {
    const pairs = features.flatMap((feature) => coordinatePairs(feature.geometry))
    if (pairs.length === 0) return null
    const lons = pairs.map(([lon]) => lon)
    const lats = pairs.map(([, lat]) => lat)
    const minLon = Math.min(...lons)
    const maxLon = Math.max(...lons)
    const minLat = Math.min(...lats)
    const maxLat = Math.max(...lats)
    const spanLon = Math.max(maxLon - minLon, Number.EPSILON)
    const spanLat = Math.max(maxLat - minLat, Number.EPSILON)
    const scale = Math.min((WIDTH - PAD * 2) / spanLon, (HEIGHT - PAD * 2) / spanLat)
    const drawWidth = spanLon * scale
    const drawHeight = spanLat * scale
    const offsetX = (WIDTH - drawWidth) / 2
    const offsetY = (HEIGHT - drawHeight) / 2
    return ([lon, lat]) => [
      offsetX + (lon - minLon) * scale,
      offsetY + (maxLat - lat) * scale,
    ]
  }, [features])

  const selected = selectedGeoid ? rowsByGeoid.get(String(selectedGeoid)) : null
  const denominatorPass =
    summary?.municipality_denominator === 78 &&
    summary?.geometry_feature_count === 78 &&
    summary?.unique_geoid_count === 78 &&
    features.length === 78

  if (!projection) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 text-sm text-slate-500">
        Municipal geometry is unavailable.
      </div>
    )
  }

  return (
    <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900" aria-labelledby="municipal-map-title">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <div>
          <h2 id="municipal-map-title" className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <MapPinned className="h-4 w-4 text-sky-400" />
            Puerto Rico Municipal Conditions
          </h2>
          <p className="mt-1 text-[11px] text-slate-500">
            Fixed island extent · select a municipio for its attached dashboard data
          </p>
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Municipal map metric">
          {Object.entries(METRICS).map(([key, meta]) => (
            <button
              key={key}
              type="button"
              onClick={() => onMetricChange?.(key)}
              aria-pressed={metric === key}
              className={`rounded-md border px-2.5 py-1 text-[11px] transition ${
                metric === key
                  ? 'border-sky-700 bg-sky-950/70 text-sky-200'
                  : 'border-slate-700 bg-slate-950/40 text-slate-400 hover:text-slate-200'
              }`}
            >
              {meta.label}
            </button>
          ))}
        </div>
      </div>

      {!denominatorPass && (
        <div className="flex items-center gap-2 border-b border-amber-900/50 bg-amber-950/30 px-4 py-2 text-xs text-amber-300">
          <AlertTriangle className="h-3.5 w-3.5" />
          Municipal map contract is incomplete: expected 78 geometry features and 78 unique GEOIDs.
        </div>
      )}

      <div className="grid lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 bg-slate-950/40 p-3">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="block h-auto w-full"
            role="group"
            aria-label={`Puerto Rico municipios colored by ${metricMeta.label.toLowerCase()}`}
          >
            {features.map((feature) => {
              const props = feature.properties ?? {}
              const geoid = String(props.geoid ?? '')
              const row = rowsByGeoid.get(geoid)
              const value = Number(row?.[metricMeta.key]) || 0
              const path = geometryPath(feature.geometry, projection)
              const isSelected = geoid && geoid === String(selectedGeoid ?? '')
              return (
                <path
                  key={geoid || props.name}
                  d={path}
                  role="button"
                  tabIndex={0}
                  aria-label={`${props.name ?? geoid}: ${metricMeta.label} ${value}`}
                  onClick={() => row && onSelect?.(row)}
                  onKeyDown={(event) => {
                    if (!row || !['Enter', ' '].includes(event.key)) return
                    event.preventDefault()
                    onSelect?.(row)
                  }}
                  className={`${bucketClass(value, maxValue)} cursor-pointer transition hover:fill-cyan-400/80 focus:outline-none ${
                    isSelected ? 'stroke-cyan-300' : 'stroke-slate-950'
                  }`}
                  strokeWidth={isSelected ? 2.5 : 0.8}
                  vectorEffect="non-scaling-stroke"
                  fillRule="evenodd"
                >
                  <title>{`${props.name}: ${metricMeta.label} ${value}`}</title>
                </path>
              )
            })}
          </svg>
          <div className="mt-2 flex items-center justify-between gap-3 text-[10px] text-slate-500">
            <span>{features.length} geometry features · {summary?.unique_geoid_count ?? 0} summary GEOIDs</span>
            <span>{metricMeta.label}: brighter → higher relative count</span>
          </div>
        </div>

        <aside className="border-t border-slate-800 bg-slate-950/55 p-4 lg:border-l lg:border-t-0" aria-live="polite">
          {!selected ? (
            <div className="flex min-h-48 items-center justify-center text-center text-sm text-slate-500">
              Select a municipio on the island to inspect its data.
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <div className="text-[10px] uppercase tracking-widest text-slate-500">Selected municipio</div>
                <h3 className="mt-1 text-lg font-semibold text-slate-100">{selected.name}</h3>
                <div className="font-mono text-[10px] text-slate-600">GEOID {selected.geoid}</div>
              </div>

              <dl className="grid grid-cols-2 gap-2 text-xs">
                {[
                  ['Assets', selected.asset_count],
                  ['Active assets', selected.active_asset_count],
                  ['Events', selected.event_count],
                  ['Active outages', selected.active_outage_count],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-md border border-slate-800 bg-slate-900/70 p-2.5">
                    <dt className="text-[10px] text-slate-500">{label}</dt>
                    <dd className="mt-1 font-mono text-base text-slate-100">{value ?? 0}</dd>
                  </div>
                ))}
              </dl>

              <div className="border-t border-slate-800 pt-3 text-xs">
                {detailLoading ? (
                  <p className="text-slate-500">Loading attached municipal detail…</p>
                ) : detail ? (
                  <div className="space-y-1.5 text-slate-400">
                    <p>Monitoring readings: <span className="text-slate-200">{detail.monitoring?.length ?? 0}</span></p>
                    <p>Asset types: <span className="text-slate-200">{detail.asset_types?.length ?? 0}</span></p>
                    <p>
                      Flood document: <span className="text-slate-200">
                        {detail.flood_document?.source_state?.replace(/_/g, ' ') ?? 'not bound'}
                      </span>
                    </p>
                  </div>
                ) : (
                  <p className="text-slate-600">No additional municipal detail returned.</p>
                )}
              </div>

              <Link
                to={`/municipios/${encodeURIComponent(selected.name)}`}
                className="inline-flex items-center gap-1.5 text-xs text-sky-400 hover:text-sky-300"
              >
                Open full municipio record <ExternalLink className="h-3 w-3" />
              </Link>
            </div>
          )}
        </aside>
      </div>
    </section>
  )
}
