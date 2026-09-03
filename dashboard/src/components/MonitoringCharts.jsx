import { useMemo, useState } from 'react'
import { useReadingsEnvelope } from '@/lib/hooks'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceArea,
} from 'recharts'
import { CHART_TOOLTIP_STYLE } from '@/lib/format'
import {
  MONITORING_SERIES,
  filterSeriesReadings,
  requireMonitoringSeries,
  seriesIdentity,
} from '@/lib/monitoring'
import { Activity, AlertCircle, Database } from 'lucide-react'

const axis = { fill: '#94a3b8', fontSize: 11 }

function QualityBadge({ quality }) {
  if (!quality) return null
  // 'not_applicable' is a historical reference series (annual peaks): its newest point
  // being years old is correct, so it must not read as a stale live feed.
  const historical = quality.freshness === 'not_applicable'
  const stale = !historical && quality.freshness !== 'fresh'
  const tone = stale
    ? 'border-amber-800 bg-amber-950/30 text-amber-300'
    : historical
      ? 'border-slate-700 bg-slate-900/60 text-slate-300'
      : 'border-emerald-900 bg-emerald-950/30 text-emerald-300'
  return (
    <div className={`rounded border px-2 py-1 text-[10px] ${tone}`}>
      {historical ? 'historical record' : quality.freshness}
      {historical ? '' : ` · ${quality.age_hours == null ? 'age unknown' : `${quality.age_hours}h old`}`}
      {' · datum '}{quality.datum_status}
      {quality.provisional_count > 0 ? ` · ${quality.provisional_count} provisional` : ''}
    </div>
  )
}

export default function MonitoringCharts() {
  const [seriesKey, setSeriesKey] = useState('reservoir_elevation')
  const [range, setRange] = useState('all')
  const [site, setSite] = useState(null)
  const series = requireMonitoringSeries(seriesKey)

  const sinceParam = range === 'all' ? undefined : (() => {
    const d = new Date()
    const days = { '7d': 7, '30d': 30, '90d': 90 }[range] || 30
    d.setDate(d.getDate() - days)
    return d.toISOString()
  })()

  const { data: envelope, isLoading } = useReadingsEnvelope({
    kind: series.sourceKind,
    metric: series.metric,
    since: sinceParam,
  })
  const sourceReadings = envelope?.items ?? []
  const quality = envelope?.quality
  const provenance = envelope?.provenance
  const readings = useMemo(
    () => filterSeriesReadings(sourceReadings, series),
    [sourceReadings, series],
  )

  const sites = useMemo(() => {
    const counts = new Map()
    for (const r of readings) {
      const id = r.site_no ?? 'unknown'
      counts.set(id, (counts.get(id) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([id, count]) => ({ id, count }))
  }, [readings])

  const activeSite = sites.some((s) => s.id === site) ? site : sites[0]?.id
  const chart = useMemo(() => (
    readings
      .filter((r) => (r.site_no ?? 'unknown') === activeSite)
      .sort((a, b) => (a.observed_date || '').localeCompare(b.observed_date || ''))
      .map((r) => ({
        name: (r.observed_date || '').slice(5),
        fullDate: r.observed_date || '',
        value: Number(r.value),
        site: r.site_no,
        identity: seriesIdentity(r),
        provisional: Boolean(r.provisional),
      }))
      .filter((r) => Number.isFinite(r.value))
  ), [readings, activeSite])

  const identities = useMemo(() => new Set(chart.map((r) => r.identity)), [chart])
  const mixedIdentity = identities.size > 1
  const { anomalySet, anomalies, gapBands } = useMemo(() => {
    if (mixedIdentity || chart.length < 5) return { anomalySet: new Set(), anomalies: [], gapBands: [] }
    const certified = chart.filter((d) => !d.provisional)
    if (certified.length < 5) return { anomalySet: new Set(), anomalies: [], gapBands: [] }
    const vals = certified.map((d) => d.value)
    const mean = vals.reduce((sum, value) => sum + value, 0) / vals.length
    const std = Math.sqrt(vals.reduce((sum, value) => sum + (value - mean) ** 2, 0) / vals.length)
    const threshold = 2 * (std || 1)
    const anomalyList = certified
      .filter((d) => Math.abs(d.value - mean) > threshold)
      .map((d) => ({ ...d, sigma: ((d.value - mean) / (std || 1)).toFixed(1) }))
      .slice(0, 6)
    const gaps = []
    for (let i = 1; i < chart.length; i += 1) {
      const prev = chart[i - 1].fullDate
      const curr = chart[i].fullDate
      if (!prev || !curr) continue
      const days = (new Date(curr) - new Date(prev)) / 86400000
      if (days > 30) gaps.push({ x1: chart[i - 1].name, x2: chart[i].name, days: Math.round(days) })
    }
    return { anomalySet: new Set(anomalyList.map((a) => a.name)), anomalies: anomalyList, gapBands: gaps }
  }, [chart, mixedIdentity])

  return (
    <div className="h-full overflow-auto p-3 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="flex items-center gap-2 text-sm font-medium text-slate-200">
            <Activity className="h-4 w-4 text-sky-300" /> Monitoring
          </h4>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
            Metric-safe observations with freshness, datum, and certification status.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-md border border-slate-800 bg-slate-950 p-0.5">
            {['7d', '30d', '90d', 'all'].map((r) => (
              <button key={r} onClick={() => setRange(r)} className={`rounded px-2 py-1 text-[10px] uppercase tracking-wide transition ${range === r ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}>{r}</button>
            ))}
          </div>
          <Select value={seriesKey} onValueChange={(value) => { setSeriesKey(value); setSite(null) }}>
            <SelectTrigger className="h-8 w-[190px] border-slate-800 bg-slate-950 text-xs" aria-label="Monitoring series"><SelectValue /></SelectTrigger>
            <SelectContent>{MONITORING_SERIES.map((item) => <SelectItem key={item.key} value={item.key} className="text-xs">{item.label}</SelectItem>)}</SelectContent>
          </Select>
          {sites.length > 1 && (
            <Select value={activeSite ?? ''} onValueChange={setSite}>
              <SelectTrigger className="h-8 w-[150px] border-slate-800 bg-slate-950 text-xs" aria-label="Monitoring site"><SelectValue placeholder="Site" /></SelectTrigger>
              <SelectContent>{sites.map((s) => <SelectItem key={s.id} value={s.id} className="text-xs">{s.id} · {s.count}</SelectItem>)}</SelectContent>
            </Select>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-3 shadow-xs">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-400">{series.label}{activeSite ? ` · site ${activeSite}` : ''} · {readings.length} readings ({series.unit})</div>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{series.note}</p>
            <p className="mt-1 text-[10px] text-slate-600">{provenance?.threshold
              ? `Threshold source: ${provenance.threshold.provenance}`
              : provenance
                ? 'Reference series — no alert threshold by design; inspect only.'
                : 'Threshold source: undeclared'}</p>
          </div>
          <div className="flex flex-col items-end gap-1"><QualityBadge quality={quality} /><div className="rounded border border-slate-800 bg-slate-950 px-2 py-1 text-[10px] text-slate-400">{chart.length} plotted</div></div>
        </div>

        {quality?.freshness === 'stale' && <div className="mb-3 rounded border border-amber-900/50 bg-amber-950/20 p-2 text-[11px] text-amber-300">This series is stale. Do not treat the latest point as current operational status.</div>}
        {quality?.datum_status === 'missing' && <div className="mb-3 rounded border border-red-900/50 bg-red-950/20 p-2 text-[11px] text-red-300">Required datum is undeclared; values remain visible but are not certified for cross-site comparison.</div>}
        {mixedIdentity && <div className="mb-3 rounded border border-amber-900/50 bg-amber-950/20 p-2 text-[11px] text-amber-300">Multiple parameter-code identities exist. Anomaly statistics are disabled.</div>}

        <div className="h-60">
          {chart.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 rounded border border-dashed border-slate-800 text-sm text-slate-500"><Database className="h-5 w-5 text-slate-600" />{isLoading ? 'Loading readings…' : 'No readings available for this exact metric and unit.'}</div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" tick={axis} />
                <YAxis tick={axis} domain={['auto', 'auto']} unit={series.unit} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                {gapBands.map((gap) => <ReferenceArea key={`${gap.x1}-${gap.x2}`} x1={gap.x1} x2={gap.x2} fill="#0f172a" fillOpacity={0.85} stroke="#334155" strokeOpacity={0.4} />)}
                <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={(props) => props.payload && anomalySet.has(props.payload.name) ? <circle key={props.index} cx={props.cx} cy={props.cy} r={5} fill="#ef4444" stroke="#7f1d1d" strokeWidth={1} /> : null} activeDot={{ r: 4, fill: '#38bdf8' }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {(anomalies.length > 0 || gapBands.length > 0) && (
          <div className="mt-3 space-y-2 border-t border-slate-800 pt-3">
            {anomalies.length > 0 && <div className="rounded border border-red-900/40 bg-red-950/20 p-2.5"><p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-red-400"><AlertCircle className="h-3 w-3" /> {anomalies.length} certified anomaly signal{anomalies.length > 1 ? 's' : ''}</p>{anomalies.map((a) => <div key={`${a.fullDate}-${a.identity}`} className="flex items-center justify-between text-[11px]"><span className="font-mono text-slate-400">{a.name}</span><span className="font-mono text-red-300">{a.value.toFixed(2)} {series.unit} ({a.sigma}σ)</span></div>)}</div>}
            {gapBands.length > 0 && <div className="rounded border border-slate-700/50 bg-slate-900/50 p-2.5"><p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Data gaps</p>{gapBands.map((gap) => <p key={`${gap.x1}-${gap.x2}`} className="font-mono text-[11px] text-slate-500">{gap.x1} → {gap.x2} <span className="text-slate-600">({gap.days}d gap)</span></p>)}</div>}
          </div>
        )}
      </div>
    </div>
  )
}
