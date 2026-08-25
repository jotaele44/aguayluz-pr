import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMunicipioSummary, useAssets, useEventsPaged } from '@/lib/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, AlertTriangle, Database, MapPin, Activity } from 'lucide-react'
import { FederationStatCard } from '@pr-federation/react'
import { fmtDate, droughtCategoryMeta, CONTAMINATION_EVENT_TYPES } from '@/lib/format'
import { MONITORING_SERIES, filterSeriesReadings } from '@/lib/monitoring'

// Thin wrapper over the shared metric tile so the call sites below keep reading
// the same. `tone` is now a canonical federation status role rather than a
// Tailwind class, so the tint is theme-aware and comes from --fd-tone-* tokens.
function StatCard({ label, value, sub, tone }) {
  return <FederationStatCard label={label} value={value ?? '–'} sub={sub} tone={tone} />
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

  // `summary.monitoring` is the raw per-site readings the backend joined from this
  // municipio's stations (server/backend/app.py `_monitoring_readings_for_assets`).
  // Reuse the same series definitions and matching logic MonitoringCharts.jsx uses,
  // rather than re-deriving which readings belong to which series here.
  const monitoringReadings = summary?.monitoring ?? []
  const monitoringTiles = useMemo(() => (
    MONITORING_SERIES
      .map((series) => {
        const matches = filterSeriesReadings(monitoringReadings, series)
        if (matches.length === 0) return null
        const latest = matches.reduce((a, b) => (
          String(b.observed_date || '') > String(a.observed_date || '') ? b : a
        ))
        return { series, latest, siteCount: new Set(matches.map((m) => m.site_no)).size }
      })
      .filter(Boolean)
  ), [monitoringReadings])

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

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
        <StatCard label="Total Assets" value={summary?.asset_count ?? assets.length} />
        <StatCard label="Active Assets" value={activeAssets.length} tone="success"
          sub={pctActive != null ? `${pctActive}% nominal` : undefined} />
        <StatCard label="Total Events" value={summary?.event_count ?? totalEvents} tone="warning" />
        <StatCard label="Active Outages"
          value={events.filter((e) => e.event_type === 'outage' && !e.end_time).length}
          tone="danger" />
        <StatCard label="Contamination"
          value={events.filter((e) => CONTAMINATION_EVENT_TYPES.includes(e.event_type) && !e.end_time).length}
          tone="danger" />
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3 flex items-center gap-2">
          <Activity className="h-3.5 w-3.5" /> Monitoring
          <span className="ml-auto text-slate-600 font-normal">Water, drought &amp; precipitation conditions</span>
        </h2>
        {monitoringTiles.length === 0
          ? <p className="text-sm text-slate-500 text-center py-8">No monitoring stations in this municipio</p>
          : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {monitoringTiles.map(({ series, latest, siteCount }) => {
                const isDrought = series.key === 'drought_category'
                const meta = isDrought ? droughtCategoryMeta(latest.value) : null
                return (
                  <div key={series.key} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">{series.label}</div>
                    <div className={`mt-1 text-lg font-semibold ${meta ? meta.tone : 'text-slate-100'}`}>
                      {isDrought ? meta.label : `${latest.value} ${series.unit}`}
                    </div>
                    <div className="mt-1 text-[10px] text-slate-600">
                      {fmtDate(latest.observed_date)}{siteCount > 1 ? ` · ${siteCount} stations` : ''}
                      {latest.provisional ? ' · provisional' : ''}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
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
