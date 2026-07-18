import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useEventsPaged, useHealth } from '@/lib/hooks'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { tierBadge, fmtDate, eventTone, EVENT_TYPES } from '@/lib/format'
import { cn } from '@/lib/utils'
import { AlertTriangle, Zap } from 'lucide-react'
import PanelState from '@/components/common/PanelState'

function eventLabel(event) {
  return (event.event_type || 'event').replace(/_/g, ' ')
}

function groupKey(event) {
  return event.municipality || event.affected_area || event.zone || 'Unassigned area'
}

export default function OutagesPanel() {
  // Bounded/paged fetch: render only the most recent slice (default limit) but
  // surface the true corpus total so the count stays honest.
  const { data: paged, isLoading } = useEventsPaged()
  const { data: health } = useHealth()
  const backendDown = health != null && health.status !== 'ok'
  const events = paged?.items ?? []
  const total = paged?.total ?? events.length
  const [q, setQ] = useState('')
  const [type, setType] = useState('all')

  const filtered = useMemo(() => events.filter((e) =>
    (type === 'all' || e.event_type === type) &&
    (!q || (e.affected_area || '').toLowerCase().includes(q.toLowerCase()) ||
           (e.municipality || '').toLowerCase().includes(q.toLowerCase()))
  ), [events, type, q])

  const groups = useMemo(() => {
    const map = new Map()
    for (const event of filtered) {
      const key = groupKey(event)
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(event)
    }
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
  }, [filtered])

  if (isLoading || !events.length) {
    return (
      <PanelState
        isLoading={isLoading}
        isError={backendDown}
        isEmpty={!events.length}
        rows={5}
        skeletonClass="h-16"
        emptyText="No service events available."
      />
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-2 py-1.5 shrink-0 border-b border-slate-800">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search area / municipio…" className="h-7 flex-1 text-xs bg-slate-950 border-slate-800" />
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="h-7 w-[130px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{EVENT_TYPES.map((t) => <SelectItem key={t} value={t} className="text-xs capitalize">{t.replace(/_/g, ' ')}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="h-full overflow-auto p-2 space-y-2">
        <div className="rounded-md border border-amber-500/20 bg-amber-500/10 p-2 text-[11px] leading-relaxed text-amber-200/90">
          <div className="mb-1 flex items-center gap-1.5 font-semibold"><AlertTriangle className="h-3.5 w-3.5" /> Snapshot caveat</div>
          Service-event records are shown as reported/snapshot-grade. Do not infer live utility attribution unless the source record explicitly supports it.
        </div>

        <div className="px-1 pb-1 text-xs text-slate-400">{filtered.length} of {events.length} recent loaded · {total.toLocaleString()} total · {groups.length} areas</div>

        {groups.map(([area, rows]) => (
          <section key={area} className="rounded-lg border border-slate-800 bg-slate-950/80">
            <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
              <Link to={`/municipios/${encodeURIComponent(area)}`} className="truncate text-xs font-semibold text-slate-100 hover:text-sky-300 transition">{area}</Link>
              <Badge variant="outline" className="border-slate-700 bg-slate-900 text-[10px] text-slate-300">{rows.length} events</Badge>
            </div>
            <div className="space-y-1.5 p-2">
              {rows.map((e) => (
                <Link key={e.event_id} to={`/events/${encodeURIComponent(e.event_id ?? '')}`} className="block rounded-md border border-slate-800 bg-slate-900 p-2.5 hover:bg-slate-800/60 transition">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Zap className={cn('h-3.5 w-3.5 shrink-0', eventTone(e.event_type))} />
                    <span className="text-xs font-medium capitalize text-slate-200">{eventLabel(e)}</span>
                    {e.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(e.evidence_tier))}>{e.evidence_tier}</Badge>}
                    <span className="ml-auto text-[11px] text-slate-500">{fmtDate(e.start_time)}</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-300">{e.affected_area || e.municipality || 'Area unavailable'}{e.zone ? ` (${e.zone})` : ''}</p>
                  {e.reported_customers_or_users != null && (
                    <p className="mt-0.5 text-[11px] text-amber-300/90">{Number(e.reported_customers_or_users).toLocaleString()} customers/users affected</p>
                  )}
                </Link>
              ))}
            </div>
          </section>
        ))}

        {filtered.length === 0 && <p className="py-8 text-center text-sm text-slate-500">No events match filters.</p>}
      </div>
    </div>
  )
}
