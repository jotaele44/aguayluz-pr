import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMunicipioSummary, useAssets, useEventsPaged } from '@/lib/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, AlertTriangle, Database, MapPin } from 'lucide-react'
import { fmtDate } from '@/lib/format'

function StatCard({ label, value, sub, tone = 'text-slate-100' }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">{label}</p>
      <p className={`text-2xl font-semibold font-mono ${tone}`}>{value ?? '–'}</p>
      {sub && <p className="text-[11px] text-slate-500 mt-1 font-mono">{sub}</p>}
    </div>
  )
}

export default function MunicipioDetailPage() {
  const { name } = useParams()
  const decoded = decodeURIComponent(name)
  const { data: summary, isLoading: summaryLoading } = useMunicipioSummary(decoded)
  const { data: assets = [], isLoading: assetsLoading } = useAssets({ municipio: decoded })
  const { data: eventsPage, isLoading: eventsLoading } = useEventsPaged({ municipio: decoded, limit: 25 })

  const events = eventsPage?.items ?? []
  const totalEvents = eventsPage?.total ?? 0

  const activeAssets = useMemo(() => assets.filter((a) => a.status === 'active' || a.status === 'operational'), [assets])
  const pctActive = assets.length > 0 ? Math.round((activeAssets.length / assets.length) * 100) : null

  if (summaryLoading || assetsLoading) {
    return (
      <div className="p-6 space-y-4 max-w-4xl">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
        </div>
        <Skeleton className="h-64 rounded-lg" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <div className="flex items-center gap-3">
        <Link to="/map" className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition">
          <ArrowLeft className="h-3.5 w-3.5" /> Map
        </Link>
        <span className="text-slate-700">/</span>
        <span className="text-sm font-semibold text-slate-200">{decoded}</span>
      </div>

      <div className="flex items-center gap-3">
        <MapPin className="h-5 w-5 text-sky-400" />
        <h1 className="text-xl font-bold text-slate-100">{decoded}</h1>
        <Badge variant="outline" className="text-xs border-slate-700">Municipio</Badge>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Total Assets" value={summary?.asset_count ?? assets.length} />
        <StatCard label="Active Assets" value={activeAssets.length} tone="text-emerald-400"
          sub={pctActive != null ? `${pctActive}% nominal` : undefined} />
        <StatCard label="Total Events" value={summary?.event_count ?? totalEvents} tone="text-amber-400" />
        <StatCard label="Active Outages"
          value={events.filter((e) => e.event_type === 'outage' && !e.end_time).length}
          tone="text-red-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3 rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3 flex items-center gap-2">
            <AlertTriangle className="h-3.5 w-3.5" /> Recent Events
            <span className="ml-auto text-slate-600 font-normal">{totalEvents.toLocaleString()} total</span>
          </h2>
          {eventsLoading
            ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 mb-2 rounded" />)
            : events.length === 0
              ? <p className="text-sm text-slate-500 text-center py-8">No events recorded</p>
              : (
                <div className="space-y-2">
                  {events.map((e, i) => (
                    <Link
                      key={e.event_id ?? i}
                      to={`/events/${encodeURIComponent(e.event_id ?? '')}`}
                      className="flex items-start gap-3 p-3 rounded-lg border border-slate-800 bg-slate-950/50 hover:bg-slate-800/50 transition"
                    >
                      <AlertTriangle className={`h-3.5 w-3.5 shrink-0 mt-0.5 ${e.event_type === 'outage' ? 'text-red-400' : 'text-amber-400'}`} />
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-slate-300 capitalize">{(e.event_type || '').replace(/_/g, ' ')}</p>
                        <p className="text-[11px] text-slate-500 truncate">{e.affected_area || e.municipality}</p>
                      </div>
                      <span className="text-[10px] font-mono text-slate-600 shrink-0">{fmtDate(e.start_time)}</span>
                    </Link>
                  ))}
                </div>
              )}
        </div>

        <div className="lg:col-span-2 rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3 flex items-center gap-2">
            <Database className="h-3.5 w-3.5" /> Assets
          </h2>
          {assets.length === 0
            ? <p className="text-sm text-slate-500 text-center py-8">No assets found</p>
            : (
              <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
                {assets.map((a) => (
                  <Link
                    key={a.asset_id}
                    to={`/assets/${a.asset_id}`}
                    className="flex items-center justify-between p-2.5 rounded-md border border-slate-800 bg-slate-950/40 hover:bg-slate-800/40 transition"
                  >
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-slate-200 truncate">{a.asset_name}</p>
                      <p className="text-[10px] text-slate-500 capitalize">{(a.asset_type || '').replace(/_/g, ' ')}</p>
                    </div>
                    <Badge
                      variant="outline"
                      className={`text-[10px] shrink-0 ml-2 ${a.status === 'active' || a.status === 'operational' ? 'border-emerald-800 text-emerald-400' : 'border-slate-700 text-slate-500'}`}
                    >
                      {a.status ?? 'unknown'}
                    </Badge>
                  </Link>
                ))}
              </div>
            )}
        </div>
      </div>
    </div>
  )
}
