import { useMemo, useState } from 'react'
import { useReadings } from '@/lib/hooks'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { READING_KINDS } from '@/lib/aguayluz-format'

const tip = { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, fontSize: 12 }
const axis = { fill: '#94a3b8', fontSize: 11 }

export default function MonitoringCharts() {
  const [kind, setKind] = useState('reservoir')
  const { data: readings = [], isLoading } = useReadings(kind)

  // Shape the data per kind: time-series for reservoir/generation, bars for reliability.
  const chart = useMemo(() => {
    if (kind === 'reliability') {
      return readings.map((r) => ({ name: `${r.metric}`.toUpperCase(), value: r.value, site: r.site_no }))
    }
    if (kind === 'generation') {
      // sum MWh by month
      const byMonth = {}
      for (const r of readings) {
        const m = (r.observed_date || '').slice(0, 7)
        if (!m) continue
        byMonth[m] = (byMonth[m] || 0) + (r.value || 0)
      }
      return Object.entries(byMonth).sort().map(([name, value]) => ({ name, value: Math.round(value) }))
    }
    // reservoir: value over observed_date
    return [...readings]
      .sort((a, b) => (a.observed_date || '').localeCompare(b.observed_date || ''))
      .map((r) => ({ name: (r.observed_date || '').slice(5), value: r.value, site: r.site_no }))
  }, [readings, kind])

  const isBar = kind === 'reliability'

  return (
    <div className="h-full overflow-auto p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-slate-200">Monitoring</h4>
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="h-7 w-[160px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{READING_KINDS.map((k) => <SelectItem key={k.key} value={k.key} className="text-xs">{k.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      <div className="rounded-md border border-slate-800 bg-slate-900 p-3">
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">
          {READING_KINDS.find((k) => k.key === kind)?.label} · {readings.length} readings
          {READING_KINDS.find((k) => k.key === kind)?.unit ? ` (${READING_KINDS.find((k) => k.key === kind).unit})` : ''}
        </div>
        <div className="h-56">
          {chart.length === 0 ? (
            <div className="h-full flex items-center justify-center text-sm text-slate-500">{isLoading ? 'Loading…' : 'No readings'}</div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              {isBar ? (
                <BarChart data={chart} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" tick={axis} />
                  <YAxis tick={axis} />
                  <Tooltip contentStyle={tip} />
                  <Bar dataKey="value" fill="#38bdf8" radius={[3, 3, 0, 0]} />
                </BarChart>
              ) : (
                <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" tick={axis} />
                  <YAxis tick={axis} domain={['auto', 'auto']} />
                  <Tooltip contentStyle={tip} />
                  <Line type="monotone" dataKey="value" stroke="#38bdf8" dot={false} strokeWidth={2} />
                </LineChart>
              )}
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  )
}
