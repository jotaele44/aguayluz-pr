import { useMemo } from 'react'
import { useEvents } from '@/lib/hooks'
import { Badge } from '@/components/ui/badge'
import { tierBadge, fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { AlertTriangle, Zap } from 'lucide-react'

const TYPE_TONE = {
  outage: 'text-red-300',
  service_interruption: 'text-amber-300',
  restoration: 'text-emerald-300',
  boil_water: 'text-sky-300',
  project_update: 'text-violet-300',
}

function eventLabel(event) {
  return (event.event_type || 'event').replace(/_/g, ' ')
}

function groupKey(event) {
  return event.municipality || event.affected_area || event.zone || 'Unassigned area'
}

export default function OutagesPanel() {
  const { data: events = [] } = useEvents()

  const groups = useMemo(() => {
    const map = new Map()
    for (const event of events) {
      const key = groupKey(event)
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(event)
    }
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
  }, [events])

  return (
    <div className="h-full overflow-auto p-2 space-y-2">
      <div className="rounded-md border border-amber-500/20 bg-amber-500/10 p-2 text-[11px] leading-relaxed text-amber-200/90">
        <div className="mb-1 flex items-center gap-1.5 font-semibold"><AlertTriangle className="h-3.5 w-3.5" /> Snapshot caveat</div>
        Service-event records are shown as reported/snapshot-grade. Do not infer live utility attribution unless the source record explicitly supports it.
      </div>

      <div className="px-1 pb-1 text-xs text-slate-400">{events.length} service events · {groups.length} affected areas</div>

      {groups.map(([area, rows]) => (
        <section key={area} className="rounded-lg border border-slate-800 bg-slate-950/80">
          <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
            <h4 className="truncate text-xs font-semibold text-slate-100">{area}</h4>
            <Badge variant="outline" className="border-slate-700 bg-slate-900 text-[10px] text-slate-300">{rows.length} events</Badge>
          </div>
          <div className="space-y-1.5 p-2">
            {rows.map((e) => (
              <div key={e.event_id} className="rounded-md border border-slate-800 bg-slate-900 p-2.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <Zap className={cn('h-3.5 w-3.5 shrink-0', TYPE_TONE[e.event_type] ?? 'text-slate-400')} />
                  <span className="text-xs font-medium capitalize text-slate-200">{eventLabel(e)}</span>
                  {e.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(e.evidence_tier))}>{e.evidence_tier}</Badge>}
                  <span className="ml-auto text-[11px] text-slate-500">{fmtDate(e.start_time)}</span>
                </div>
                <p className="mt-1 text-xs text-slate-300">{e.affected_area || e.municipality || 'Area unavailable'}{e.zone ? ` (${e.zone})` : ''}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                  {e.reported_customers_or_users != null && (
                    <span className="font-medium text-amber-300/90">{Number(e.reported_customers_or_users).toLocaleString()} customers/users affected</span>
                  )}
                  {e.source_ref && <span className="truncate">source: {e.source_ref}</span>}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}

      {events.length === 0 && <p className="py-8 text-center text-sm text-slate-500">No service events are available from the backend.</p>}
    </div>
  )
}
