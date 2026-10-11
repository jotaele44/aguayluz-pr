import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CloudRain, Database, Droplets, Loader2, RefreshCw, ShieldCheck, Waves } from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import Panel from '@/components/common/Panel'
import PanelState from '@/components/common/PanelState'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/use-toast'
import { getApiKey } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { useHealth, useSystemStatus } from '@/lib/hooks'
import {
  useHydrometRefresh,
  useHydrometSources,
  useHydrometSummary,
  useRainfall,
  useRiverGauges,
} from '@/lib/hydromet-hooks'
import { cn } from '@/lib/utils'

// FRESH: last success within the source's max age. STALE: older. FAILED: the latest
// attempt failed (the last success, if any, is still shown). NEVER: no receipt yet.
const FRESHNESS_STYLE = {
  FRESH: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  STALE: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  FAILED: 'border-red-500/40 bg-red-500/10 text-red-300',
  NEVER: 'border-slate-600 bg-slate-800/60 text-slate-300',
}

const FLOOD_CATEGORY_STYLE = {
  major: 'border-fuchsia-500/50 bg-fuchsia-500/15 text-fuchsia-200',
  moderate: 'border-red-500/50 bg-red-500/15 text-red-200',
  minor: 'border-orange-500/50 bg-orange-500/15 text-orange-200',
  action: 'border-yellow-500/50 bg-yellow-500/15 text-yellow-200',
  no_flooding: 'border-emerald-600/40 bg-emerald-600/10 text-emerald-300',
  low_threshold: 'border-sky-600/40 bg-sky-600/10 text-sky-300',
  not_defined: 'border-slate-700 bg-slate-800/50 text-slate-400',
  obs_not_current: 'border-slate-600 bg-slate-800/50 text-slate-400',
}

const THRESHOLD_ORDER = ['action', 'minor', 'moderate', 'major']

const pretty = (value) => String(value || 'unknown').replaceAll('_', ' ')

const RAIN_WINDOWS = [
  { id: '1day', label: '1 day' },
  { id: 'last7days', label: '7 days' },
  { id: 'last30days', label: '30 days' },
]

const HEAVY_RAIN_STYLE = {
  3: 'border-fuchsia-500/50 bg-fuchsia-500/15 text-fuchsia-200',
  2: 'border-orange-500/50 bg-orange-500/15 text-orange-200',
}

const inches = (value) => (value == null ? '—' : `${Number(value).toFixed(2)} in`)

const cadenceText = (seconds) => {
  const minutes = Math.round((seconds ?? 0) / 60)
  return minutes >= 120 ? `${Math.round(minutes / 60)} h` : `${minutes} min`
}

const ageText = (seconds) => {
  if (seconds == null) return '—'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} d ago`
}

function Badge({ className, children }) {
  return (
    <span className={cn('inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium', className)}>
      {children}
    </span>
  )
}

function SourceCard({ source, refreshReady, refreshHint, refreshing, onRefresh }) {
  const receipt = source.receipt
  const success = receipt?.last_success
  const arithmetic = success?.arithmetic
  const state = source.freshness?.state ?? 'NEVER'
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4" data-testid={`hydromet-source-${source.source_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-100">{source.label}</div>
          <div className="text-xs text-slate-500">{source.authority}</div>
        </div>
        <Badge className={FRESHNESS_STYLE[state]}>{state}</Badge>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
        <div><dt className="inline text-slate-500">Last success: </dt><dd className="inline text-slate-300">{receipt?.last_success_utc ? `${fmtDate(receipt.last_success_utc)} (${ageText(source.freshness?.age_seconds)})` : 'never'}</dd></div>
        <div><dt className="inline text-slate-500">Last attempt: </dt><dd className="inline text-slate-300">{receipt?.last_attempt_utc ? `${fmtDate(receipt.last_attempt_utc)} — ${receipt.last_status}` : 'never'}</dd></div>
        <div><dt className="inline text-slate-500">Arithmetic: </dt><dd className="inline text-slate-300">{arithmetic ? `${arithmetic.source} source = ${arithmetic.retained} retained + ${arithmetic.excluded} excluded + ${arithmetic.unresolved} unresolved (${arithmetic.state})` : '—'}</dd></div>
        <div><dt className="inline text-slate-500">Expected cadence: </dt><dd className="inline text-slate-300">every {cadenceText(source.cadence_seconds)}, stale after {Math.round((source.max_age_seconds ?? 0) / 3600)} h</dd></div>
        <div className="sm:col-span-2"><dt className="inline text-slate-500">Source bytes SHA-256: </dt><dd className="inline break-all font-mono text-[11px] text-slate-400">{success?.byte_sha256 ?? '—'}</dd></div>
        <div className="sm:col-span-2"><dt className="inline text-slate-500">Endpoint: </dt><dd className="inline break-all font-mono text-[11px] text-slate-400">{success?.source_url ?? source.endpoints?.gauges ?? source.endpoints?.grid ?? '—'}</dd></div>
      </dl>
      {receipt?.last_status === 'FAIL' && (
        <div role="alert" className="mt-3 rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-200">
          Latest attempt failed: {receipt.last_error}
        </div>
      )}
      {source.known_limits && <p className="mt-3 text-[11px] leading-relaxed text-slate-500">{source.known_limits}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          variant="outline"
          disabled={!refreshReady || refreshing}
          onClick={() => onRefresh(source.source_id)}
          className="h-8 border-slate-700 bg-slate-950 text-xs text-slate-300 hover:text-slate-100"
        >
          {refreshing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
          {refreshing ? 'Refreshing…' : 'Refresh now'}
        </Button>
        <span className="text-[11px] text-slate-500">{refreshHint}</span>
      </div>
    </div>
  )
}

function ThresholdCell({ thresholds, unit }) {
  const defined = THRESHOLD_ORDER.filter((name) => thresholds?.[name]?.stage != null)
  if (!defined.length) return <span className="text-slate-600">none published</span>
  return (
    <span className="text-slate-400">
      {defined.map((name) => `${name} ${thresholds[name].stage}`).join(' · ')} {unit || ''}
    </span>
  )
}

function GaugeTable({ gauges }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-left text-xs" aria-label="NWPS river gauges">
        <thead className="text-[11px] uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="py-2 pr-3 font-medium">Gauge</th>
            <th className="py-2 pr-3 font-medium">Municipio</th>
            <th className="py-2 pr-3 font-medium">Flood category</th>
            <th className="py-2 pr-3 font-medium">Observed</th>
            <th className="py-2 pr-3 font-medium">NWS thresholds</th>
            <th className="py-2 pr-3 font-medium">Linked asset</th>
          </tr>
        </thead>
        <tbody>
          {gauges.map((g) => (
            <tr key={g.lid} className="border-b border-slate-900 align-top">
              <td className="py-2 pr-3">
                <div className="font-medium text-slate-200">{g.name}</div>
                <div className="font-mono text-[11px] text-slate-500">{g.lid}{g.usgs_id ? ` · USGS ${g.usgs_id}` : ''}</div>
              </td>
              <td className="py-2 pr-3 text-slate-300">
                {g.municipio ?? <span className="text-amber-300">unresolved{g.county_raw ? ` (NWPS: ${g.county_raw})` : ''}</span>}
                <div className="text-[11px] text-slate-500">{pretty(g.binding_evidence)}</div>
              </td>
              <td className="py-2 pr-3">
                <Badge className={FLOOD_CATEGORY_STYLE[g.flood_category] ?? FLOOD_CATEGORY_STYLE.not_defined}>{pretty(g.flood_category)}</Badge>
              </td>
              <td className="py-2 pr-3 text-slate-300">
                {g.observed?.stage != null ? `${g.observed.stage} ${g.observed.stage_unit ?? ''}` : '—'}
                <div className={cn('text-[11px]', g.observation_stale ? 'text-amber-300' : 'text-slate-500')}>
                  {g.observed?.valid_time ? fmtDate(g.observed.valid_time) : 'no observation'}{g.observation_stale ? ' · stale' : ''}
                </div>
              </td>
              <td className="py-2 pr-3"><ThresholdCell thresholds={g.thresholds} unit={g.threshold_stage_unit} /></td>
              <td className="py-2 pr-3">
                {g.asset_id
                  ? <Link className="text-sky-300 hover:underline" to={`/map?flyTo=${encodeURIComponent(g.asset_id)}&lat=${g.latitude}&lon=${g.longitude}`}>{g.asset_id}</Link>
                  : <span className="text-slate-600">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RainfallTable({ rows, windowDays }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-xs" aria-label="Stage IV rainfall by municipio">
        <thead className="text-[11px] uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="py-2 pr-3 font-medium">Municipio</th>
            <th className="py-2 pr-3 font-medium">Mean ({windowDays} d)</th>
            <th className="py-2 pr-3 font-medium">Wettest cell</th>
            <th className="py-2 pr-3 font-medium">PRISM normal</th>
            <th className="py-2 pr-3 font-medium">% of normal</th>
            <th className="py-2 pr-3 font-medium">HRAP cells</th>
            <th className="py-2 pr-3 font-medium">Heavy rain</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.record_id} className="border-b border-slate-900 align-top">
              <td className="py-2 pr-3">
                <Link className="font-medium text-sky-300 hover:underline" to={`/municipios/${encodeURIComponent(r.municipio)}`}>{r.municipio}</Link>
                <div className="font-mono text-[11px] text-slate-500">{r.geoid}</div>
              </td>
              <td className="py-2 pr-3 text-slate-200">{inches(r.obs_mean_in)}</td>
              <td className="py-2 pr-3 text-slate-300">{inches(r.obs_max_in)}</td>
              <td className="py-2 pr-3 text-slate-400">{inches(r.normal_mean_in)}</td>
              <td className="py-2 pr-3 text-slate-400">{r.pct_of_normal == null ? '—' : `${r.pct_of_normal}%`}</td>
              <td className="py-2 pr-3 text-slate-400">
                {r.cell_count ?? '—'}
                {r.method && r.method !== 'raster_cell_centres_in_polygon' && <div className="text-[11px] text-amber-300">{pretty(r.method)}</div>}
              </td>
              <td className="py-2 pr-3">
                {r.heavy_rain_severity
                  ? <Badge className={HEAVY_RAIN_STYLE[r.heavy_rain_severity]}>severity {r.heavy_rain_severity}</Badge>
                  : <span className="text-slate-600">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RainfallPanel({ up }) {
  const [rainWindow, setRainWindow] = useState('1day')
  const [day, setDay] = useState('')
  const rainfallQuery = useRainfall({ window: rainWindow, date: day || undefined })
  const rainfall = rainfallQuery.data
  const rows = rainfall?.items ?? []
  const thresholds = rainfall?.thresholds
  const heavy = rows.filter((r) => r.heavy_rain_severity).length
  return (
    <Panel>
      <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">Rainfall by municipio (Stage IV)</h2>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-xs text-slate-500">
          NWS Stage IV radar + gauge analysis, 12Z to 12Z, summarised over the 4.76 km HRAP cells whose centres fall
          inside each municipio. Published after the day closes: use it for follow-up, not warning.
          {thresholds && ` Heavy rain: municipio mean ≥ ${thresholds.mean_in} in (severity 2) or any cell ≥ ${thresholds.cell_max_in} in (severity 3), 1-day window only.`}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1" role="group" aria-label="Rainfall window">
            {RAIN_WINDOWS.map((w) => (
              <Button
                key={w.id}
                size="sm"
                variant="outline"
                aria-pressed={rainWindow === w.id}
                onClick={() => { setRainWindow(w.id); setDay('') }}
                className={cn('h-7 border-slate-700 text-xs', rainWindow === w.id ? 'bg-sky-500/15 text-sky-200' : 'bg-slate-950 text-slate-300')}
              >
                {w.label}
              </Button>
            ))}
          </div>
          <select
            aria-label="Rainfall data day"
            value={day || rainfall?.data_date || ''}
            onChange={(event) => setDay(event.target.value)}
            disabled={!(rainfall?.available_dates?.length > 1)}
            className="h-7 rounded border border-slate-700 bg-slate-950 px-2 text-xs text-slate-300 disabled:opacity-50"
          >
            {(rainfall?.available_dates?.length ? rainfall.available_dates : ['']).map((d) => (
              <option key={d || 'none'} value={d}>{d ? `ending ${d} 12Z` : 'no data day'}</option>
            ))}
          </select>
        </div>
      </div>
      {rainfall?.data_date && (
        <div className="mb-3 text-[11px] text-slate-500" data-testid="rainfall-provenance">
          {rows.length} municipios · {rainWindow === '1day' ? `${heavy} at a heavy-rain threshold` : 'heavy-rain flags apply to the 1-day window'}
          {(rainfall.files ?? []).map((f) => (
            <div key={f.manifestation_id} className="mt-1 break-all font-mono">
              {f.source_record_id} · SHA-256 {f.byte_sha256.slice(0, 16)}… · retrieved {fmtDate(f.retrieved_at)}
            </div>
          ))}
        </div>
      )}
      <PanelState
        isLoading={rainfallQuery.isLoading}
        isError={!up && !rows.length}
        isEmpty={!rows.length}
        emptyText="No Stage IV rainfall ingested yet. Use Refresh now on the Stage IV source above."
      >
        <RainfallTable rows={rows} windowDays={rainfall?.window_days ?? 1} />
      </PanelState>
    </Panel>
  )
}

export default function HydrometPage() {
  const [floodingOnly, setFloodingOnly] = useState(false)
  const summaryQuery = useHydrometSummary()
  const sourcesQuery = useHydrometSources()
  const gaugesQuery = useRiverGauges({ flooding_only: floodingOnly })
  const { data: health, isError: healthError } = useHealth()
  const { data: status } = useSystemStatus()
  const refresh = useHydrometRefresh()
  const { toast } = useToast()

  const summary = summaryQuery.data
  const sources = sourcesQuery.data?.sources ?? []
  const gauges = gaugesQuery.data?.items ?? []
  const up = health?.status === 'ok' && !healthError
  const authNeedsKey = Boolean(status?.auth_enabled) && !getApiKey()
  const refreshReady = up && !authNeedsKey
  const refreshHint = !up
    ? 'Unavailable — the backend is unreachable.'
    : authNeedsKey
      ? 'Unavailable — API_SECRET_KEY is set on the backend. Enter the key in System & Tools.'
      : 'Fetches the source now, then rebuilds alerts. Scheduled runs continue regardless.'

  const runRefresh = (sourceId) => refresh.mutate(sourceId, {
    onSuccess: (result) => toast({
      title: 'Hydromet refresh complete',
      description: `${sourceId}: ${result?.receipt?.last_success?.arithmetic?.retained ?? 0} records retained; alerts rebuilt.`,
    }),
    onError: (error) => toast({ variant: 'destructive', title: 'Hydromet refresh failed', description: String(error?.message ?? error) }),
  })

  const counts = summary?.counts
  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="NWS Hydromet"
        subtitle="Puerto Rico river and reservoir flood status and rainfall from NOAA/NWS, with source freshness and provenance"
      />
      <div className="min-h-0 flex-1 space-y-5 overflow-auto p-6">
        <ErrorBoundary label="NWS hydromet plane">
          <div role="note" aria-label="Hydromet scope" className="flex items-start gap-3 rounded-lg border border-sky-500/30 bg-sky-500/10 p-4">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" aria-hidden="true" />
            <p className="text-sm text-sky-100/90">
              {summary?.scope?.statement ?? 'Hydromet observations are hazard context, not confirmed damage or service impact.'}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {[
              { label: 'Gauges', value: counts?.gauges ?? '—', icon: Waves },
              { label: 'In flood', value: counts?.gauges_in_flood ?? '—', icon: CloudRain },
              { label: 'Stale observations', value: counts?.gauges_stale ?? '—', icon: Database },
              { label: 'Heavy rain (1 day)', value: summary?.rainfall_latest_date ? counts?.rainfall_heavy ?? 0 : '—', icon: Droplets },
              { label: 'Integrity', value: summary?.integrity?.state ?? '—', icon: ShieldCheck },
            ].map(({ label, value, icon: Icon }) => (
              <div key={label} className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
                <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500"><Icon className="h-4 w-4" aria-hidden="true" />{label}</div>
                <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
              </div>
            ))}
          </div>

          <Panel>
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">Source health</h2>
            <PanelState isLoading={sourcesQuery.isLoading} isError={!up && !sources.length} isEmpty={!sources.length} rows={2} emptyText="No hydromet sources registered.">
              <div className="space-y-3">
                {sources.map((source) => (
                  <SourceCard
                    key={source.source_id}
                    source={source}
                    refreshReady={refreshReady}
                    refreshHint={refreshHint}
                    refreshing={refresh.isPending && refresh.variables === source.source_id}
                    onRefresh={runRefresh}
                  />
                ))}
              </div>
            </PanelState>
          </Panel>

          <Panel>
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">River and reservoir gauges (NWPS)</h2>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-slate-500">
                Observed stage against NWS-published flood thresholds. NWS issues no stage forecasts for Puerto Rico points.
              </p>
              <Button
                size="sm"
                variant="outline"
                aria-pressed={floodingOnly}
                onClick={() => setFloodingOnly((v) => !v)}
                className={cn('h-7 border-slate-700 text-xs', floodingOnly ? 'bg-orange-500/15 text-orange-200' : 'bg-slate-950 text-slate-300')}
              >
                {floodingOnly ? 'Showing gauges in flood' : 'Show only gauges in flood'}
              </Button>
            </div>
            <PanelState
              isLoading={gaugesQuery.isLoading}
              isError={!up && !gauges.length}
              isEmpty={!gauges.length}
              emptyText={floodingOnly ? 'No gauge is at or above its action stage.' : 'No gauge state yet — run a refresh.'}
            >
              <GaugeTable gauges={gauges} />
            </PanelState>
          </Panel>

          <RainfallPanel up={up} />
        </ErrorBoundary>
      </div>
    </div>
  )
}
