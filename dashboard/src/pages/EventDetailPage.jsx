import { Link, useParams } from 'react-router-dom'
import { useEvent, useAssets } from '@/lib/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { ArrowLeft, AlertTriangle, Calendar, MapPin, Users, Link2, Clock } from 'lucide-react'
import { fmtDate } from '@/lib/format'

const TYPE_COLOR = {
  outage: 'text-red-400 border-red-900 bg-red-950/20',
  service_interruption: 'text-amber-400 border-amber-900 bg-amber-950/20',
  restoration: 'text-emerald-400 border-emerald-900 bg-emerald-950/20',
  boil_water: 'text-orange-400 border-orange-900 bg-orange-950/20',
}

function Field({ label, children }) {
  if (!children) return null
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-0.5">{label}</dt>
      <dd className="text-sm text-slate-200">{children}</dd>
    </div>
  )
}

export default function EventDetailPage() {
  const { id } = useParams()
  const { data: event, isLoading, isError } = useEvent(id)
  const { data: assets = [] } = useAssets()

  const linkedAssets = (event?.linked_asset_ids ?? [])
    .map((aid) => assets.find((a) => a.asset_id === aid))
    .filter(Boolean)

  if (isLoading) {
    return (
      <div className="p-6 space-y-4 max-w-2xl">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
    )
  }

  if (isError || !event) {
    return (
      <div className="p-6">
        <Link to="/outages" className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 mb-4">
          <ArrowLeft className="h-4 w-4" /> Back to Outages
        </Link>
        <p className="text-slate-400 text-sm">Event not found or failed to load.</p>
      </div>
    )
  }

  const typeClass = TYPE_COLOR[event.event_type] ?? 'text-slate-400 border-slate-700 bg-slate-800/20'
  const isActive = !event.end_time || event.resolution_status !== 'resolved'

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div className="flex items-center gap-3">
        <Link to="/outages" className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition">
          <ArrowLeft className="h-3.5 w-3.5" /> Outages
        </Link>
        <span className="text-slate-700">/</span>
        <span className="text-xs font-mono text-slate-400 truncate">{id}</span>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className={`h-5 w-5 ${typeClass.split(' ')[0]}`} />
              <h1 className="text-lg font-semibold text-slate-100 capitalize">
                {(event.event_type || 'Event').replace(/_/g, ' ')}
              </h1>
            </div>
            <Badge variant="outline" className={`text-xs capitalize ${typeClass}`}>
              {event.resolution_status ?? (isActive ? 'active' : 'closed')}
            </Badge>
          </div>
          {isActive && (
            <span className="inline-flex items-center gap-1.5 text-xs text-red-300 bg-red-950/30 border border-red-900/40 rounded-full px-2.5 py-1">
              <span className="h-1.5 w-1.5 rounded-full bg-red-400 animate-pulse" />
              Active
            </span>
          )}
        </div>

        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Event ID"><span className="font-mono text-xs">{event.event_id}</span></Field>
          <Field label="Affected Area">{event.affected_area}</Field>
          <Field label="Municipality">{event.municipality}</Field>
          <Field label="Sector">{event.sector}</Field>
          <Field label="Start Time">
            <span className="flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5 text-slate-500" />
              {fmtDate(event.start_time) || '–'}
            </span>
          </Field>
          <Field label="End Time">
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-slate-500" />
              {fmtDate(event.end_time) || 'Ongoing'}
            </span>
          </Field>
          {event.affected_customers != null && (
            <Field label="Affected Customers">
              <span className="flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5 text-slate-500" />
                {event.affected_customers.toLocaleString()}
              </span>
            </Field>
          )}
          {event.source_ref && (
            <Field label="Source">
              {/^https?:\/\//.test(event.source_ref)
                ? <a href={event.source_ref} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sky-400 hover:text-sky-300 text-xs break-all"><Link2 className="h-3.5 w-3.5 shrink-0" />{event.source_ref}</a>
                : <span className="font-mono text-xs">{event.source_ref}</span>
              }
            </Field>
          )}
        </dl>

        {event.description && (
          <div className="mt-4 pt-4 border-t border-slate-800">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Description</p>
            <p className="text-sm text-slate-300 leading-relaxed">{event.description}</p>
          </div>
        )}
      </div>

      {linkedAssets.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3 flex items-center gap-2">
            <MapPin className="h-3.5 w-3.5" /> Linked Assets ({linkedAssets.length})
          </h2>
          <div className="space-y-2">
            {linkedAssets.map((a) => (
              <Link
                key={a.asset_id}
                to={`/assets/${a.asset_id}`}
                className="flex items-center justify-between p-3 rounded-lg border border-slate-800 bg-slate-950/50 hover:bg-slate-800/50 transition"
              >
                <div>
                  <p className="text-sm font-medium text-slate-200">{a.asset_name}</p>
                  <p className="text-xs text-slate-500">{a.asset_type} · {a.municipality}</p>
                </div>
                <Badge variant="outline" className="text-xs capitalize">{a.status}</Badge>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
