import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useHealth, useAssets, useEvents, useReadings, useSummarySectors } from '@/lib/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Activity, AlertTriangle, CheckCircle2, Clock, Zap, Droplets, Radio, Trash2 } from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { fmtDate } from '@/lib/format'

const SECTOR_META = {
  power: { label: 'Power', icon: Zap, color: 'text-amber-400', border: 'border-amber-500/30', bg: 'bg-amber-500/5' },
  water: { label: 'Water', icon: Droplets, color: 'text-sky-400', border: 'border-sky-500/30', bg: 'bg-sky-500/5' },
  wastewater: { label: 'Wastewater', icon: Trash2, color: 'text-emerald-400', border: 'border-emerald-500/30', bg: 'bg-emerald-500/5' },
  telecom: { label: 'Telecom', icon: Radio, color: 'text-violet-400', border: 'border-violet-500/30', bg: 'bg-violet-500/5' },
}

const TOOLTIP_STYLE = {
  background: 'hsl(222 47% 11%)',
  border: '1px solid hsl(217 33% 17%)',
  borderRadius: 8,
  fontSize: 11,
  color: 'hsl(210 40% 96%)',
}

export default function OverviewPage() {
  const { data: health, isLoading: healthLoading } = useHealth()
  const { data: assets = [], isLoading: assetsLoading } = useAssets()
  const { data: events = [], isLoading: eventsLoading } = useEvents()
  const { data: sectors } = useSummarySectors()
  const { data: readings = [] } = useReadings({ kind: 'reservoir' })

  const isLoading = healthLoading || assetsLoading || eventsLoading

  const c = health?.counts ?? {}
  const r = health?.readiness ?? {}

  const activeOutages = useMemo(
    () => events.filter((e) => e.event_type === 'outage'),
    [events],
  )

  const recentEvents = useMemo(
    () => [...events].sort((a, b) => (b.start_time ?? '').localeCompare(a.start_time ?? '')).slice(0, 5),
    [events],
  )

  const chartData = useMemo(() => {
    if (!readings.length) return []
    return readings
      .slice(-30)
      .map((r) => ({
        t: r.timestamp ?? r.date ?? '',
        v: r.level_pct ?? r.value ?? 0,
      }))
  }, [readings])

  if (isLoading) {
    return (
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-lg" />)}
        </div>
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-32 rounded-lg" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-[1400px]">
      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Kpi icon={Activity} label="Total Assets" value={c.assets ?? assets.length} />
        <Kpi icon={AlertTriangle} label="Active Outages" value={activeOutages.length} valueClass="text-red-400" />
        <Kpi icon={CheckCircle2} label="Grid Coverage" value={r.coverage_pct != null ? `${r.coverage_pct}%` : '–'} valueClass="text-emerald-400" />
        <Kpi icon={Clock} label="Pending Review" value={r.records_review ?? '–'} valueClass="text-amber-400" />
      </div>

      {/* Sector cards */}
      <div>
        <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">Infrastructure Sectors</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {Object.entries(SECTOR_META).map(([key, meta]) => {
            const s = sectors?.[key] ?? {}
            return (
              <Link key={key} to={`/sector/${key}`} className={`block rounded-lg border ${meta.border} ${meta.bg} p-4 hover:brightness-110 transition-all`}>
                <div className="flex items-center gap-2 mb-3">
                  <meta.icon className={`h-4 w-4 ${meta.color}`} />
                  <span className={`text-xs font-semibold uppercase tracking-wider ${meta.color}`}>{meta.label}</span>
                </div>
                <p className="text-2xl font-semibold font-mono text-slate-100">{s.total ?? '–'}</p>
                <p className="text-[11px] text-slate-500 font-mono mt-1">
                  {s.active ?? '–'} active · {s.pct_active ?? 0}% nominal
                </p>
              </Link>
            )
          })}
        </div>
      </div>

      {/* Chart + Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-lg p-5">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4">Reservoir Levels (last 30 readings)</h3>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis dataKey="t" hide />
                <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={() => ''} formatter={(v) => [`${v}%`, 'Level']} />
                <Area type="monotone" dataKey="v" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.1} strokeWidth={1.5} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-slate-500 text-center py-12">No reservoir data available</p>
          )}
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4">Recent Events</h3>
          {recentEvents.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">No events</p>
          ) : (
            <div className="space-y-2">
              {recentEvents.map((e) => (
                <div key={e.event_id} className="flex items-start gap-2 p-2.5 rounded-md bg-slate-800/50 border border-slate-700/50">
                  <AlertTriangle className={`h-3.5 w-3.5 shrink-0 mt-0.5 ${e.event_type === 'outage' ? 'text-red-400' : 'text-amber-400'}`} />
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-slate-200 truncate capitalize">{(e.event_type || '').replace(/_/g, ' ')}</p>
                    <p className="text-[11px] text-slate-500 truncate">{e.affected_area}</p>
                    <p className="text-[10px] text-slate-600 font-mono">{fmtDate(e.start_time)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Kpi({ icon: Icon, label, value, valueClass = 'text-slate-100' }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center gap-2 text-xs text-slate-400 font-mono uppercase tracking-wider mb-2">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className={`text-2xl font-semibold font-mono ${valueClass}`}>{value}</p>
    </div>
  )
}
