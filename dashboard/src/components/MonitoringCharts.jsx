import { useMemo, useState } from 'react'
import { useReadings } from '@/lib/hooks'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceArea,
} from 'recharts'
import { READING_KINDS, CHART_TOOLTIP_STYLE } from '@/lib/format'
import { Activity, AlertCircle, Database } from 'lucide-react'

const axis = { fill: '#94a3b8', fontSize: 11 }
const SOURCE_NOTE = {
  reservoir: 'Reservoir readings are source-derived time series. Missing records are left blank rather than interpolated.',
  generation: 'Generation is summed by observed month from available records.',
  reliability: 'Reliability metrics are shown as reported values; compare labels before drawing operational conclusions.',
}

export default function MonitoringCharts() {
  const [kind, setKind] = useState('reservoir')
  const [range, setRange] = useState('all')

  const sinceParam = range === 'all' ? undefined : (() => {
    const d = new Date()
    const days = { '7d': 7, '30d': 30, '90d': 90 }[range] || 30
    d.setDate(d.getDate() - days)
    return d.toISOString()
  })()

  const { data: readings = [], isLoading } = useReadings({ kind, since: sinceParam })

  const chart = useMemo(() => {
    if (kind === 'reliability') {
      return readings.map((r) => ({ name: `${r.metric}`.toUpperCase(), value: r.value, site: r.site_no }))
    }
    if (kind === 'generation') {
      const byMonth = {}
      for (const r of readings) {
        const month = (r.observed_date || '').slice(0, 7)
        if (!month) continue
        byMonth[month] = (byMonth[month] || 0) + (Number(r.value) || 0)
      }
      return Object.entries(byMonth).sort().map(([name, value]) => ({ name, value: Math.round(value) }))
    }
    return [...readings]
      .sort((a, b) => (a.observed_date || '').localeCompare(b.observed_date || ''))
      .map((r) => ({ name: (r.observed_date || '').slice(5), fullDate: r.observed_date || '', value: r.value, site: r.site_no }))
  }, [readings, kind])

  const meta = READING_KINDS.find((k) => k.key === kind)
  const isBar = kind === 'reliability'

  const { anomalySet, anomalies, gapBands } = useMemo(() => {
    if (isBar || chart.length < 5) return { anomalySet: new Set(), anomalies: [], gapBands: [] }
    const vals = chart.map((d) => Number(d.value)).filter((v) => !Number.isNaN(v))
    if (vals.length < 5) return { anomalySet: new Set(), anomalies: [], gapBands: [] }
    const mean = vals.reduce((s, v) => s + v, 0) / vals.length
    const std = Math.sqrt(vals.reduce((s, v) => s + (v - mean) ** 2, 0) / vals.length)
    const threshold = 2 * (std || 1)
    const anomalyList = chart
      .filter((d) => d.value != null && Math.abs(Number(d.value) - mean) > threshold)
      .map((d) => ({ ...d, sigma: ((Number(d.value) - mean) / (std || 1)).toFixed(1) }))
      .slice(0, 6)
    const aSet = new Set(anomalyList.map((a) => a.name))
    const gaps = []
    if (kind === 'reservoir' && chart.length > 1) {
      for (let i = 1; i < chart.length; i++) {
        const prev = chart[i - 1].fullDate
        const curr = chart[i].fullDate
        if (!prev || !curr) continue
        const days = (new Date(curr) - new Date(prev)) / 86400000
        if (days > 30) {
          gaps.push({ x1: chart[i - 1].name, x2: chart[i].name, days: Math.round(days) })
        }
      }
    }
    return { anomalySet: aSet, anomalies: anomalyList, gapBands: gaps }
  }, [chart, isBar, kind])

  return (
    <div className="h-full overflow-auto p-3 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="flex items-center gap-2 text-sm font-medium text-slate-200"><Activity className="h-4 w-4 text-sky-300" /> Monitoring</h4>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Reservoir, generation, and grid-reliability observations from the repo backend.</p>
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
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger className="h-8 w-[160px] border-slate-800 bg-slate-950 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{READING_KINDS.map((k) => <SelectItem key={k.key} value={k.key} className="text-xs">{k.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900 p-3 shadow-sm">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-400">
              {meta?.label} · {readings.length} readings{meta?.unit ? ` (${meta.unit})` : ''}
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{SOURCE_NOTE[kind]}</p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950 px-2 py-1 text-[10px] text-slate-400">
            {chart.length} plotted
          </div>
        </div>
        <div className="h-60">
          {chart.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 rounded border border-dashed border-slate-800 text-sm text-slate-500">
              <Database className="h-5 w-5 text-slate-600" />
              {isLoading ? 'Loading readings…' : 'No readings available for this metric.'}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              {isBar ? (
                <BarChart data={chart} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" tick={axis} />
                  <YAxis tick={axis} />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Bar dataKey="value" fill="#38bdf8" radius={[3, 3, 0, 0]} />
                </BarChart>
              ) : (
                <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" tick={axis} />
                  <YAxis tick={axis} domain={['auto', 'auto']} />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  {gapBands.map((gap, i) => (
                    <ReferenceArea key={i} x1={gap.x1} x2={gap.x2} fill="#0f172a" fillOpacity={0.85} stroke="#334155" strokeOpacity={0.4} />
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
              )}
            </ResponsiveContainer>
          )}
        </div>

        {(anomalies.length > 0 || gapBands.length > 0) && (
          <div className="mt-3 space-y-2 border-t border-slate-800 pt-3">
            {anomalies.length > 0 && (
              <div className="rounded border border-red-900/40 bg-red-950/20 p-2.5">
                <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-red-400 mb-2">
                  <AlertCircle className="h-3 w-3" /> {anomalies.length} anomalous reading{anomalies.length > 1 ? 's' : ''} (&gt;2σ from mean)
                </p>
                <div className="space-y-1">
                  {anomalies.map((a) => (
                    <div key={a.name} className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400 font-mono">{a.name}{a.site ? ` · ${a.site}` : ''}</span>
                      <span className="text-red-300 font-mono">{Number(a.value).toFixed(2)} ({a.sigma}σ)</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {gapBands.length > 0 && (
              <div className="rounded border border-slate-700/50 bg-slate-900/50 p-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
                  Data gaps (shaded gray on chart)
                </p>
                <div className="space-y-0.5">
                  {gapBands.map((g, i) => (
                    <p key={i} className="text-[11px] text-slate-500 font-mono">
                      {g.x1} → {g.x2} <span className="text-slate-600">({g.days}d gap)</span>
                    </p>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
