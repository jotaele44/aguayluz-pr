import { useParams, Link } from 'react-router-dom'
import { useMemo } from 'react'
import { useAssets, useEvents, useSummarySectors } from '@/lib/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { statusTone, CHART_TOOLTIP_STYLE } from '@/lib/format'
import { SECTOR_META } from '@/lib/sectors'
import Panel from '@/components/common/Panel'

export default function SectorDetailPage() {
  const { sector } = useParams()
  const meta = SECTOR_META[sector]
  const { data: assets = [], isLoading: aLoad } = useAssets()
  const { data: events = [], isLoading: eLoad } = useEvents()
  const { data: sectors } = useSummarySectors()
  const isLoading = aLoad || eLoad

  const sectorAssets = useMemo(
    () => assets.filter((a) => meta?.types.some((t) => (a.asset_type || '').toLowerCase().includes(t))),
    [assets, meta],
  )

  const sectorEvents = useMemo(() => {
    const muns = new Set(sectorAssets.map((a) => (a.municipality || '').toLowerCase()).filter(Boolean))
    return events.filter((e) => muns.has((e.municipality || '').toLowerCase()))
  }, [events, sectorAssets])

  const byStatus = useMemo(() => {
    const counts = {}
    for (const a of sectorAssets) {
      const s = a.status || 'unknown'
      counts[s] = (counts[s] || 0) + 1
    }
    return Object.entries(counts).map(([name, value]) => ({ name, value }))
  }, [sectorAssets])

  if (!meta) return <div className="p-6 text-slate-400">Unknown sector: {sector}</div>

  const s = sectors?.[sector] ?? {}

  return (
    <div className="p-6 space-y-6 max-w-[1400px]">
      <div className="flex items-center gap-3">
        <Link to="/" className="text-slate-500 hover:text-slate-300 transition-colors">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <meta.icon className={`h-5 w-5 ${meta.color}`} />
        <h1 className="text-xl font-semibold text-slate-100">{meta.label} Infrastructure</h1>
        <span className="text-slate-500 text-sm ml-1">
          {s.total ?? sectorAssets.length} assets · {s.pct_active ?? 0}% active
        </span>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-64 rounded-lg" />)}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Panel title="Asset Status">
              {byStatus.length > 0 ? (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={byStatus} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                    <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                    <Bar dataKey="value" fill="#38bdf8" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-slate-500 text-center py-8">No data</p>
              )}
            </Panel>

            <Panel title={`Related Events (${sectorEvents.length})`}>
              <div className="space-y-1.5 max-h-[190px] overflow-auto">
                {sectorEvents.slice(0, 10).map((e, i) => (
                  <div key={e.event_id ?? i} className="flex items-center gap-2 text-xs py-1.5 border-b border-slate-800 last:border-0">
                    <span className="text-slate-400 capitalize shrink-0">{(e.event_type || '').replace(/_/g, ' ')}</span>
                    <span className="text-slate-500 truncate">{e.affected_area}</span>
                    <span className="ml-auto text-slate-600 font-mono text-[10px] shrink-0">{e.start_time?.slice(0, 10)}</span>
                  </div>
                ))}
                {sectorEvents.length === 0 && <p className="text-slate-500 text-xs">No related events</p>}
              </div>
            </Panel>
          </div>

          <Panel title={`Assets (${sectorAssets.length})`}>
            <div className="overflow-auto max-h-[400px]">
              <table className="w-full text-xs text-slate-300">
                <thead className="sticky top-0 bg-slate-900">
                  <tr className="border-b border-slate-800 text-slate-500 text-left">
                    <th scope="col" className="py-2 pr-4 font-medium">Name</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Type</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Municipality</th>
                    <th scope="col" className="py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {sectorAssets.slice(0, 100).map((a) => (
                    <tr key={a.asset_id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="py-2 pr-4 max-w-[240px] truncate">{a.asset_name}</td>
                      <td className="py-2 pr-4 text-slate-500 capitalize">{a.asset_type}</td>
                      <td className="py-2 pr-4 text-slate-500">{a.municipality || '—'}</td>
                      <td className="py-2">
                        <span {...statusTone(a.status, 'text-[10px] capitalize')}>{a.status || '—'}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {sectorAssets.length > 100 && (
                <p className="text-xs text-slate-500 text-center py-2">Showing 100 of {sectorAssets.length}</p>
              )}
            </div>
          </Panel>
        </>
      )}
    </div>
  )
}
