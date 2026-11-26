import { useMemo, useRef, useState } from 'react'
import { AlertTriangle, Download, RefreshCw } from 'lucide-react'

import DroughtMap from '@/components/DroughtMap'
import { useAssetsGeojson, useMunicipiosGeojson } from '@/lib/hooks'
import { useRainfall, useRiverGaugesGeojson } from '@/lib/hydromet-hooks'
import {
  useDroughtAlertsGeojson,
  useDroughtFootprint,
  useDroughtOutageEvents,
  useDroughtOutageStatus,
  useDroughtReservoirReadings,
  useDroughtSummary,
} from '@/lib/drought-hooks'

const CATEGORY_META = {
  D0: { label: 'Abnormally dry', color: '#ffff00' },
  D1: { label: 'Moderate drought', color: '#fcd37f' },
  D2: { label: 'Severe drought', color: '#ffaa00' },
  D3: { label: 'Extreme drought', color: '#e60000' },
  D4: { label: 'Exceptional drought', color: '#730000' },
  None: { label: 'No designation', color: '#64748b' },
}

function formatPercent(value) {
  const number = Number(value)
  return Number.isFinite(number) ? `${number.toFixed(number % 1 ? 1 : 0)}%` : '—'
}

function latestDate(rows, key = 'observed_date') {
  return (rows || []).map((row) => row?.[key]).filter(Boolean).sort().at(-1) || null
}

function latestFeatureTime(collection, key) {
  return (collection?.features || [])
    .map((feature) => feature?.properties?.[key])
    .filter(Boolean)
    .sort()
    .at(-1) || null
}

function freshnessTone(state) {
  if (state === 'FRESH') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
  if (state === 'STALE') return 'border-amber-500/40 bg-amber-500/10 text-amber-300'
  return 'border-slate-700 bg-slate-900 text-slate-400'
}

function SourceRow({ label, value, detail, warning = false }) {
  return (
    <div className="grid grid-cols-[115px_1fr] gap-2 border-b border-slate-800/70 py-2 last:border-0">
      <div className="text-[11px] font-medium text-slate-300">{label}</div>
      <div>
        <div className={`text-[11px] ${warning ? 'text-amber-300' : 'text-slate-200'}`}>{value || 'Unavailable'}</div>
        {detail && <div className="mt-0.5 text-[10px] leading-relaxed text-slate-500">{detail}</div>}
      </div>
    </div>
  )
}

function Panel({ title, children }) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-950/70">
      <h2 className="border-b border-slate-800 px-3 py-2 text-xs font-semibold text-slate-200">{title}</h2>
      <div className="p-3">{children}</div>
    </section>
  )
}

export default function DroughtPage() {
  const mapRef = useRef(null)
  const [selectedMunicipio, setSelectedMunicipio] = useState(null)
  const [selectedFootprint, setSelectedFootprint] = useState(null)

  const summaryQuery = useDroughtSummary()
  const footprintQuery = useDroughtFootprint()
  const reservoirQuery = useDroughtReservoirReadings()
  const alertQuery = useDroughtAlertsGeojson()
  const outageEventsQuery = useDroughtOutageEvents()
  const outageStatusQuery = useDroughtOutageStatus()
  const municipioQuery = useMunicipiosGeojson()
  const assetsQuery = useAssetsGeojson()
  const gaugeQuery = useRiverGaugesGeojson()
  const rainfallQuery = useRainfall({ window: '1day' })

  const summary = summaryQuery.data
  const footprint = footprintQuery.data
  const rainfall = rainfallQuery.data
  const reservoirs = reservoirQuery.data || []
  const alerts = alertQuery.data
  const outageEvents = outageEventsQuery.data || []
  const outageStatus = outageStatusQuery.data

  const rainByGeoid = useMemo(() => Object.fromEntries(
    (rainfall?.items || [])
      .filter((row) => row.geoid && Number.isFinite(Number(row.obs_mean_in)))
      .map((row) => [row.geoid, Number(row.obs_mean_in)]),
  ), [rainfall])

  const municipioByName = useMemo(() => new Map(
    (summary?.municipios || [])
      .filter((row) => row.municipio)
      .map((row) => [row.municipio, row]),
  ), [summary])

  const groupedMunicipios = useMemo(() => {
    const groups = { D4: [], D3: [], D2: [], D1: [], D0: [], None: [] }
    for (const row of summary?.municipios || []) {
      const key = row.category in groups ? row.category : 'None'
      groups[key].push(row.municipio || row.geoid)
    }
    for (const values of Object.values(groups)) values.sort((a, b) => a.localeCompare(b))
    return groups
  }, [summary])

  const selectedMunicipioRow = selectedMunicipio
    ? municipioByName.get(selectedMunicipio.name)
    : null

  const directOutageCount = outageEvents.filter((row) => (
    Number.isFinite(Number(row?.lat)) && Number.isFinite(Number(row?.lon))
  )).length

  const queries = [
    summaryQuery,
    footprintQuery,
    reservoirQuery,
    alertQuery,
    outageEventsQuery,
    outageStatusQuery,
    gaugeQuery,
    rainfallQuery,
  ]
  const refreshing = queries.some((query) => query.isFetching)

  const refreshView = () => {
    for (const query of queries) query.refetch?.()
  }

  const stats = summary?.statistics
  const change = summary?.change
  const history = (summary?.history || []).slice(-8).reverse()
  const footprintAvailable = summary?.status === 'available' && (footprint?.features?.length || 0) > 0

  const latestReservoir = latestDate(reservoirs)
  const latestGauge = latestFeatureTime(gaugeQuery.data, 'valid_time')
  const latestAlertCount = alerts?.features?.length || 0
  const latestOutage = outageStatus?.latest?.snapshot_ts || null

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold text-slate-100">Puerto Rico Drought Operations</h1>
            <span className={`rounded border px-2 py-0.5 text-[10px] font-semibold ${freshnessTone(summary?.freshness?.state)}`}>
              {summary?.freshness?.state || 'UNKNOWN'}
            </span>
          </div>
          <div className="mt-0.5 text-[11px] text-slate-500">
            USDM weekly footprint + independent AguaYLuz operational layers · map date {summary?.map_date || 'unavailable'}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={refreshView}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:text-white disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh view
          </button>
          <button
            type="button"
            onClick={() => mapRef.current?.exportSnapshot?.()}
            disabled={!footprintAvailable}
            className="inline-flex items-center gap-1.5 rounded border border-sky-500/40 bg-sky-500/10 px-3 py-1.5 text-xs text-sky-200 hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Download className="h-3.5 w-3.5" />
            Export PNG
          </button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_430px]">
        <main className="min-h-[560px] p-3 xl:min-h-0">
          {footprintAvailable ? (
            <DroughtMap
              ref={mapRef}
              footprint={footprint}
              municipios={municipioQuery.data}
              assets={assetsQuery.data}
              gauges={gaugeQuery.data}
              alerts={alerts}
              outageEvents={outageEvents}
              rainByGeoid={rainByGeoid}
              mapDate={summary.map_date}
              statistics={stats}
              selectedMunicipio={selectedMunicipio?.name}
              onMunicipioSelect={setSelectedMunicipio}
              onFootprintSelect={setSelectedFootprint}
            />
          ) : (
            <div className="flex h-full min-h-[520px] items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/5 p-8 text-center">
              <div className="max-w-lg">
                <AlertTriangle className="mx-auto h-8 w-8 text-amber-300" />
                <div className="mt-3 text-sm font-semibold text-amber-200">USDM footprint unavailable</div>
                <p className="mt-2 text-xs leading-relaxed text-slate-400">
                  AguaYLuz has not promoted a current official vector footprint into this surface. This state is not interpreted as “no drought.”
                </p>
              </div>
            </div>
          )}
        </main>

        <aside className="min-h-0 overflow-y-auto border-l border-slate-800 bg-slate-950 p-3">
          <div className="space-y-3">
            <Panel title="Current USDM status">
              <div className="grid grid-cols-5 gap-1.5">
                {['D0', 'D1', 'D2', 'D3', 'D4'].map((category) => (
                  <div key={category} className="rounded-lg border border-slate-800 bg-slate-900/70 p-2 text-center">
                    <div className="mx-auto mb-1 h-2 w-8 rounded" style={{ backgroundColor: CATEGORY_META[category].color }} />
                    <div className="text-[10px] font-semibold text-slate-300">{category}</div>
                    <div className="mt-0.5 text-sm font-semibold text-slate-100">{formatPercent(stats?.[category])}</div>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
                Percentages are cumulative area shares: D2 includes land also classified D3/D4. They are not mutually exclusive bins and must not be summed.
              </p>
              {selectedFootprint?.category && (
                <div className="mt-2 rounded border border-sky-500/30 bg-sky-500/5 p-2 text-[11px] text-sky-200">
                  Selected footprint: <strong>{selectedFootprint.category}</strong> · {CATEGORY_META[selectedFootprint.category]?.label}
                </div>
              )}
              {selectedMunicipio?.name && (
                <div className="mt-2 rounded border border-slate-700 bg-slate-900/70 p-2 text-[11px] text-slate-300">
                  <div className="font-medium text-slate-100">{selectedMunicipio.name}</div>
                  <div className="mt-0.5">
                    Municipio classification: <strong>{selectedMunicipioRow?.category || 'unknown'}</strong>
                    {summary?.municipio_date && <> · {summary.municipio_date}</>}
                  </div>
                </div>
              )}
            </Panel>

            <Panel title="What changed">
              {change ? (
                <>
                  <div className="text-xs font-medium text-slate-200">
                    {change.from_map_date} → {change.to_map_date}
                    <span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] ${
                      change.direction === 'worsened'
                        ? 'bg-red-500/10 text-red-300'
                        : change.direction === 'improved'
                          ? 'bg-emerald-500/10 text-emerald-300'
                          : 'bg-slate-800 text-slate-400'
                    }`}>
                      {change.direction}
                    </span>
                  </div>
                  <div className="mt-2 grid grid-cols-5 gap-1 text-center">
                    {['D0', 'D1', 'D2', 'D3', 'D4'].map((category) => {
                      const value = change.delta_percentage_points?.[category]
                      return (
                        <div key={category} className="rounded bg-slate-900 px-1 py-1.5">
                          <div className="text-[9px] text-slate-500">{category}</div>
                          <div className="text-[11px] text-slate-200">
                            {Number.isFinite(Number(value)) ? `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(1)} pp` : '—'}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  <div className="mt-2 text-[10px] text-slate-500">{change.basis}</div>
                </>
              ) : (
                <div className="text-[11px] text-slate-500">A previous official week is not available for comparison.</div>
              )}
            </Panel>

            <Panel title="Operational layer freshness">
              <SourceRow
                label="USDM footprint"
                value={summary?.map_date}
                detail={`Weekly analysis · ${summary?.freshness?.state || 'UNKNOWN'} · ${summary?.freshness?.age_days ?? '—'} days old`}
                warning={summary?.freshness?.state !== 'FRESH'}
              />
              <SourceRow
                label="Rainfall"
                value={rainfall?.data_date}
                detail="NWS Stage IV 1-day municipio mean · query checks hourly"
              />
              <SourceRow
                label="River gauges"
                value={latestGauge}
                detail={`NWPS · ${gaugeQuery.data?.features?.length || 0} mapped gauges · query checks every 5 min`}
              />
              <SourceRow
                label="Reservoir/USGS"
                value={latestReservoir}
                detail={`${reservoirs.length} retained reservoir-series rows · query checks every 15 min`}
              />
              <SourceRow
                label="Power outages"
                value={latestOutage}
                detail={`${directOutageCount}/${outageEvents.length} outage events have direct coordinates; regional MiLUMA schema remains ${outageStatus?.schema_state || 'unknown'}`}
              />
              <SourceRow
                label="AguaYLuz alerts"
                value={`${latestAlertCount} mapped active alerts`}
                detail="Operational alert query checks every 60 sec; each alert retains its own source timestamp."
              />
              <SourceRow
                label="Rationing"
                value="Not mapped"
                detail="No authoritative geospatial rationing feed is registered. AguaYLuz does not infer rationing from drought color, low flow or outage text."
                warning
              />
            </Panel>

            <Panel title="Affected municipios">
              {summary?.municipio_date !== summary?.map_date && (
                <div className="mb-2 rounded border border-amber-500/30 bg-amber-500/5 p-2 text-[10px] text-amber-300">
                  Municipio classifications ({summary?.municipio_date || 'unknown'}) do not match the footprint map date ({summary?.map_date || 'unknown'}); lists below are not promoted as same-week geometry.
                </div>
              )}
              <div className="space-y-2">
                {['D4', 'D3', 'D2', 'D1', 'D0'].map((category) => (
                  <div key={category}>
                    <div className="flex items-center gap-2 text-[10px]">
                      <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: CATEGORY_META[category].color }} />
                      <span className="font-semibold text-slate-300">{category}</span>
                      <span className="text-slate-500">{groupedMunicipios[category].length} municipios</span>
                    </div>
                    {groupedMunicipios[category].length > 0 && (
                      <div className="mt-1 text-[10px] leading-relaxed text-slate-500">
                        {groupedMunicipios[category].join(', ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="8-week history">
              {history.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px]" aria-label="USDM Puerto Rico recent history">
                    <thead>
                      <tr className="text-left text-slate-500">
                        <th className="pb-1 font-medium">Map date</th>
                        {['D0', 'D1', 'D2', 'D3', 'D4'].map((category) => <th key={category} className="pb-1 text-right font-medium">{category}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((row) => (
                        <tr key={row.map_date} className="border-t border-slate-800/70">
                          <td className="py-1 text-slate-300">{row.map_date}</td>
                          {['D0', 'D1', 'D2', 'D3', 'D4'].map((category) => (
                            <td key={category} className="py-1 text-right text-slate-400">{formatPercent(row[category])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="text-[11px] text-slate-500">No official history retained yet.</div>}
            </Panel>

            <Panel title="Source & methodology">
              <div className="space-y-2 text-[10px] leading-relaxed text-slate-500">
                <p>
                  Authority: <span className="text-slate-300">{summary?.authority || 'NDMC/USDM'}</span>. USDM is a weekly broad-scale analysis; local conditions can vary.
                </p>
                <div>
                  <div className="text-slate-400">Geometry SHA-256</div>
                  <code className="break-all text-[9px] text-slate-500">{summary?.source_manifestations?.geometry?.sha256 || 'unavailable'}</code>
                </div>
                <div>
                  <div className="text-slate-400">Statistics SHA-256</div>
                  <code className="break-all text-[9px] text-slate-500">{summary?.source_manifestations?.statistics?.sha256 || 'unavailable'}</code>
                </div>
                <p>
                  Native drought boundaries come only from the date-specific official USDM vector. AguaYLuz selects Puerto Rico multipart components; it does not draw, interpolate, smooth or infer drought boundaries.
                </p>
                <p>
                  Supporting operational layers retain independent timestamps and do not change the USDM classification. Correlation on this page is not a root-cause determination.
                </p>
              </div>
            </Panel>
          </div>
        </aside>
      </div>
    </div>
  )
}
