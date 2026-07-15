import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useHealth, useAssets, useEvents, useReadings, useSummarySectors } from '@/lib/hooks'
import { postAiQuery, postNotify } from '@/lib/api'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/use-toast'
import { Activity, AlertTriangle, Bell, Bot, CheckCircle2, Clock, Loader2, Zap, Droplets, Radio, Trash2 } from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { fmtDate, CHART_TOOLTIP_STYLE } from '@/lib/format'
import { SECTOR_META } from '@/lib/sectors'
import Panel from '@/components/common/Panel'
import StatTile from '@/components/common/StatTile'

export default function OverviewPage() {
  const { data: health, isLoading: healthLoading } = useHealth()
  const { data: assets = [], isLoading: assetsLoading } = useAssets()
  const { data: events = [], isLoading: eventsLoading } = useEvents()
  const { data: sectors } = useSummarySectors()
  const { data: readings = [] } = useReadings({ kind: 'reservoir' })
  const [aiSummary, setAiSummary] = useState(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [notifying, setNotifying] = useState(false)
  const { toast } = useToast()

  const isLoading = healthLoading || assetsLoading || eventsLoading

  const c = health?.counts ?? {}
  const r = health?.readiness ?? {}

  const handleSummarize = async () => {
    setAiLoading(true)
    setAiSummary(null)
    const result = await postAiQuery(
      `AguaYLuz-PR dashboard status: ${c.assets ?? assets.length} assets tracked, ` +
      `${activeOutages.length} active outages, ${c.events ?? events.length} events recorded, ` +
      `${r.records_review ?? 0} records awaiting human review, ` +
      `grid coverage ${r.coverage_pct != null ? r.coverage_pct + '%' : 'unknown'}. ` +
      `Provide a 2-3 sentence plain-language status brief for a Puerto Rico infrastructure operator, ` +
      `highlighting what needs urgent attention.`
    )
    setAiSummary(result?.answer ?? result?.error ?? 'No response received.')
    setAiLoading(false)
  }

  const activeOutages = useMemo(
    () => events.filter((e) => e.event_type === 'outage'),
    [events],
  )

  const handleNotify = async () => {
    setNotifying(true)
    const msg = `AguaYLuz-PR Dashboard Alert: ${activeOutages.length} active outages across Puerto Rico. ` +
      `${c.assets ?? assets.length} assets tracked. ${r.records_review ?? 0} records awaiting review.`
    const result = await postNotify({ message: msg, title: 'AguaYLuz-PR Status Alert' })
    setNotifying(false)
    if (result?.channels_active) {
      toast({ title: 'Alert dispatched', description: `Sent to configured channels${result.errors?.length ? ` (${result.errors.length} error(s))` : ''}` })
    } else {
      toast({ variant: 'destructive', title: 'No channels configured', description: 'Set SLACK_WEBHOOK_URL, NTFY_TOPIC, or SMTP_HOST in the backend environment.' })
    }
  }

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
        <StatTile icon={Activity} label="Total Assets" value={c.assets ?? assets.length} />
        <StatTile icon={AlertTriangle} label="Active Outages" value={activeOutages.length} valueClass="text-red-400" />
        <StatTile icon={CheckCircle2} label="Grid Coverage" value={r.coverage_pct != null ? `${r.coverage_pct}%` : '–'} valueClass="text-emerald-400" />
        <StatTile icon={Clock} label="Pending Review" value={r.records_review ?? '–'} valueClass="text-amber-400" />
      </div>

      {/* AI status recap + notifications */}
      <div className="flex items-start gap-3 flex-wrap">
        <button
          onClick={handleSummarize}
          disabled={aiLoading}
          className="shrink-0 flex items-center gap-1.5 rounded-md border border-sky-700/50 bg-sky-950/40 px-3 py-1.5 text-xs text-sky-300 hover:bg-sky-900/40 hover:border-sky-600/60 disabled:opacity-50 transition"
        >
          {aiLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bot className="h-3.5 w-3.5" />}
          {aiLoading ? 'Summarizing…' : 'AI Status Recap'}
        </button>
        <button
          onClick={handleNotify}
          disabled={notifying}
          title="Send current status alert to Slack / ntfy / email (configured in backend env)"
          className="shrink-0 flex items-center gap-1.5 rounded-md border border-amber-700/40 bg-amber-950/20 px-3 py-1.5 text-xs text-amber-300 hover:bg-amber-900/30 hover:border-amber-600/50 disabled:opacity-50 transition"
        >
          {notifying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bell className="h-3.5 w-3.5" />}
          {notifying ? 'Sending…' : 'Send Alert'}
        </button>
        {aiSummary && (
          <div className="flex-1 min-w-0 rounded-lg border border-sky-900/40 bg-sky-950/20 px-4 py-2.5 text-sm text-slate-300 leading-relaxed">
            {aiSummary}
          </div>
        )}
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
        <Panel title="Reservoir Levels (last 30 readings)" className="lg:col-span-2">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis dataKey="t" hide />
                <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} labelFormatter={() => ''} formatter={(v) => [`${v}%`, 'Level']} />
                <Area type="monotone" dataKey="v" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.1} strokeWidth={1.5} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-slate-500 text-center py-12">No reservoir data available</p>
          )}
        </Panel>

        <Panel title="Recent Events">
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
        </Panel>
      </div>
    </div>
  )
}
