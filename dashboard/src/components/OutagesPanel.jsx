import { useEvents } from '@/lib/hooks'
import { Badge } from '@/components/ui/badge'
import { tierBadge, fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Zap } from 'lucide-react'

const TYPE_TONE = {
  outage: 'text-red-300',
  service_interruption: 'text-amber-300',
  restoration: 'text-emerald-300',
  boil_water: 'text-sky-300',
  project_update: 'text-violet-300',
}

// Water/power service events (outages, interruptions, boil-water).
export default function OutagesPanel() {
  const { data: events = [] } = useEvents()

  return (
    <div className="h-full overflow-auto p-2 space-y-1.5">
      <div className="px-1 pb-1 text-xs text-slate-400">{events.length} service events</div>
      {events.map((e) => (
        <div key={e.event_id} className="rounded-md border border-slate-800 bg-slate-900 p-2.5">
          <div className="flex items-center gap-2 flex-wrap">
            <Zap className={cn('h-3.5 w-3.5 shrink-0', TYPE_TONE[e.event_type] ?? 'text-slate-400')} />
            <span className="text-xs font-medium text-slate-200 capitalize">{(e.event_type || '').replace(/_/g, ' ')}</span>
            <Badge variant="outline" className={cn('text-[10px]', tierBadge(e.evidence_tier))}>{e.evidence_tier}</Badge>
            <span className="text-[11px] text-slate-500 ml-auto">{fmtDate(e.start_time)}</span>
          </div>
          <p className="text-xs text-slate-300 mt-1">{e.affected_area}{e.municipality ? ` · ${e.municipality}` : ''}{e.zone ? ` (${e.zone})` : ''}</p>
          {e.reported_customers_or_users != null && (
            <p className="text-[11px] text-amber-300/90 mt-0.5">{e.reported_customers_or_users.toLocaleString()} customers/users affected</p>
          )}
        </div>
      ))}
      {events.length === 0 && <p className="text-center text-sm text-slate-500 py-8">No events</p>}
    </div>
  )
}
