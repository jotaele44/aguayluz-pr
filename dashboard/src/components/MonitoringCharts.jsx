import { useMemo, useState } from 'react'
import { useReadings } from '@/lib/hooks'
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

  // The backend's legacy `kind=reservoir` corpus is multi-metric.  Request the
  // source corpus, but fail closed in the client by retaining only the exact
  // metric/unit declared by the selected canonical series.
  const { data: sourceReadings = [], isLoading } = useReadings({
    kind: series.sourceKind,
    metric: series.metric,
    since: sinceParam,
  })
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
    // Statistics are prohibited across parameter-code or unit boundaries.
    if (mixedIdentity || chart.length < 5) {
      return { anomalySet: new Set(), anomalies: [], gapBands: [] }
    }
    const vals = chart.map((d) => d.value)
    const mean = vals.reduce((sum, value) => sum + value, 0) / vals.length
    const std = Math.sqrt(vals.reduce((sum, value) => sum + (value - mean) ** 2, 0) / vals.length)
    const threshold = 2 * (std || 1)
    const anomalyList = chart
      .filter((d) => Math.abs(d.value - mean) > threshold)
      .map((d) => ({ ...d, sigma: ((d.value - mean) / (std || 1)).toFixed(1) }))
      .slice(0, 6)
    const aSet = new Set(anomalyList.map((a) => a.name))
    const gaps = []
    for (let i = 1; i < chart.length; i += 1) {
      const prev = chart[i - 1].fullDate
      const curr = chart[i].fullDate
      if (!prev || !curr) continue
      const days = (new Date(curr) - new Date(prev)) / 86400000
      if (days > 30) gaps.push({ x1: chart[i - 1].name, x2: chart[i].name, days: Math.round(days) })
    }
    return { anomalySet: aSet, anomalies: anomalyList, gapBands: gaps }
  }, [chart, mixedIdentity])

  return (
    <div className="h-full overflow-auto p-3 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="flex items-center gap-2 text-sm font-medium text-slate-200">
            <Activity className="h-4 w-4 text-sky-300" /> Monitoring
          </h4>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
            Metric-safe reservoir, stream, groundwater, and coastal observations.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-md border border-slate-800 bg-slate-950 p-0.5">
            {['7d', '30d', '90d', 'all'].map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={`rounded px-2 py-1 text-[10px] uppercase tracking-wide transition ${range === r ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
              >
                {r}
              </button>
            ))}
          </div>
          <Select value={seriesKey} onValueChange={(value) => { setSeriesKey(value); setSite(null) }}>
            <SelectTrigger className="h-8 w-[190px] border-slate-800 bg-slate-950 text-xs" aria-label="Monitoring series">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MONITORING_SERIES.map((item) => (
                <SelectItem key={item.key} value={item.key} className="text-xs">{item.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {sites.length > 1 && (
            <Select value={activeSite ?? ''} onValueChange={setSite}>
              <SelectTrigger className="h-8 w-[150px] border-slate-800 bg-slate-950 text-xs" aria-label="Monitoring site">
                <SelectValue placeholder="Site" />
              </SelectTrigger>
              <SelectContent>
                {sites.map((s) => (
                  <SelectItem key={s.id} value={s.id} className="text-xs">{s.id} · {s.count}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-3 shadow-sm">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-400">
              {series.label}{activeSite ? ` · site ${activeSite}` : ''} · {readings.length} readings across {sites.length} site(s) ({series.unit})
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{series.note}</p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950 px-2 py-1 text-[10px] text-slate-400">{chart.length} plotted</div>
        </div>

        {mixedIdentity && (
          <div className="mb-3 rounded border border-amber-900/50 bg-amber-950/20 p-2 text-[11px] text-amber-300">
            Multiple parameter-code series exist for this site. Values remain visible, but anomaly statistics are disabled to prevent mixed-series calculations.
          </div>
        )}

        <div className="h-60">
          {chart.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 rounded border border-dashed border-slate-800 text-sm text-slate-500">
              <Database className="h-5 w-5 text-slate-600" />
              {isLoading ? 'Loading readings…' : 'No readings available for this exact metric and unit.'}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" tick={axis} />
                <YAxis tick={axis} domain={['auto', 'auto']} unit={series.unit} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                {gapBands.map((gap) => (
                  <ReferenceArea key={`${gap.x1}-${gap.x2}`} x1={gap.x1} x2={gap.x2} fill="#0f172a" fillOpacity={0.85} stroke="#334155" strokeOpacity={0.4} />
                ))}
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={(props) => {
                    if (props.payload && anomalySet.has(props.payload.name)) {
                      return <circle key={props.index} cx={props.cx} cy={props.cy} r={5} fill="#ef4444" stroke="#7f1d1d" strokeWidth={1} />
                    }
                    return null
                  }}
                  activeDot={{ r: 4, fill: '#38bdf8' }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {(anomalies.length > 0 || gapBands.length > 0) && (
          <div className="mt-3 space-y-2 border-t border-slate-800 pt-3">
            {anomalies.length > 0 && (
              <div className="rounded border border-red-900/40 bg-red-950/20 p-2.5">
                <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-red-400">
                  <AlertCircle className="h-3 w-3" /> {anomalies.length} anomalous reading{anomalies.length > 1 ? 's' : ''} (&gt;2σ from this exact series)
                </p>
                <div className="space-y-1">
                  {anomalies.map((a) => (
                    <div key={`${a.fullDate}-${a.identity}`} className="flex items-center justify-between text-[11px]">
                      <span className="font-mono text-slate-400">{a.name}{a.provisional ? ' · provisional' : ''}</span>
                      <span className="font-mono text-red-300">{a.value.toFixed(2)} {series.unit} ({a.sigma}σ)</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {gapBands.length > 0 && (
              <div className="rounded border border-slate-700/50 bg-slate-900/50 p-2.5">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Data gaps</p>
                {gapBands.map((gap) => (
                  <p key={`${gap.x1}-${gap.x2}`} className="font-mono text-[11px] text-slate-500">
                    {gap.x1} → {gap.x2} <span className="text-slate-600">({gap.days}d gap)</span>
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
