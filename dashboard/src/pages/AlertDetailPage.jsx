import { Link, useParams } from 'react-router-dom'
import { useAlert, useAlertDependencies, useAssets } from '@/lib/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import {
  alertModuleMeta, alertSeverityMeta, gapBadge, tierBadge, fmtDate, isAlertCritical,
} from '@/lib/format'
import { cn } from '@/lib/utils'
import {
  ArrowLeft, Calendar, Clock, Link2, MapPin, Network, ShieldAlert, Flag,
} from 'lucide-react'

function Field({ label, children }) {
  if (children == null || children === '') return null
  return (
    <div>
      <dt className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-200">{children}</dd>
    </div>
  )
}

// An asset is only reachable on the map when it has geometry; the rest of the corpus
// is searchable but unplottable, so link it to the filtered assets list instead of a
// map pin that would never appear.
function assetHref(asset, id) {
  if (asset && typeof asset.lat === 'number' && typeof asset.lon === 'number') {
    return `/map?flyTo=${encodeURIComponent(id)}&lat=${asset.lat}&lon=${asset.lon}`
  }
  return `/assets?q=${encodeURIComponent(id)}`
}

export default function AlertDetailPage() {
  const { id } = useParams()
  const { data: alert, isLoading, isError } = useAlert(id)
  const { data: assets = [] } = useAssets()
  const { data: edges = [] } = useAlertDependencies({ alert_id: id })

  if (isLoading) {
    return (
      <div className="max-w-3xl space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-56 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
    )
  }

  if (isError || !alert) {
    return (
      <div className="p-6">
        <Link to="/alerts" className="mb-4 flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200">
          <ArrowLeft className="h-4 w-4" /> Back to Alerts
        </Link>
        <p className="text-sm text-slate-400">Alert not found or failed to load.</p>
      </div>
    )
  }

  const mod = alertModuleMeta(alert.module_id)
  const sev = alertSeverityMeta(alert.severity)
  const critical = alert.is_critical ?? isAlertCritical(alert)
  const linkedIds = alert.linked_asset_ids ?? []
  const covertFlags = alert.covert_flags ?? []

  return (
    <div className="max-w-3xl space-y-6 p-6">
      <div className="flex items-center gap-3">
        <Link to="/alerts" className="flex items-center gap-1.5 text-xs text-slate-500 transition hover:text-slate-300">
          <ArrowLeft className="h-3.5 w-3.5" /> Alerts
        </Link>
        <span className="text-slate-700">/</span>
        <span className="truncate font-mono text-xs text-slate-400">{alert.alert_id}</span>
      </div>

      <div className={cn(
        'rounded-xl border bg-slate-900 p-6',
        critical ? 'border-red-900/60' : 'border-slate-800',
      )}>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <ShieldAlert className={cn('h-5 w-5', sev.tone)} />
              <h1 className="text-lg font-semibold text-slate-100">
                {alert.source_title || alert.alert_id}
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className={cn('text-xs', mod.badge)}>{mod.label}</Badge>
              <span className={cn('text-xs font-medium', sev.tone)}>
                Severity {alert.severity} · {sev.label}
              </span>
              {alert.evidence_tier && (
                <Badge variant="outline" className={cn('text-[10px]', tierBadge(alert.evidence_tier))}>
                  {alert.evidence_tier}
                </Badge>
              )}
              <Badge variant="outline" className={cn('text-[10px]', gapBadge(alert.gap_status))}>
                gap: {alert.gap_status || 'none'}
              </Badge>
            </div>
          </div>
          {critical && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-red-900/40 bg-red-950/30 px-2.5 py-1 text-xs text-red-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-400" />
              Life-safety critical
            </span>
          )}
        </div>

        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Status"><span className="capitalize">{alert.status}</span></Field>
          <Field label="Review status"><span className="capitalize">{(alert.review_status || '').replace(/_/g, ' ')}</span></Field>
          <Field label="Start">
            <span className="flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5 text-slate-500" />{fmtDate(alert.start_at) || '–'}
            </span>
          </Field>
          <Field label="End">
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-slate-500" />{fmtDate(alert.end_at) || 'Ongoing'}
            </span>
          </Field>
          <Field label="Confidence">{alert.confidence != null ? `${alert.confidence}/100` : null}</Field>
          <Field label="ILAP score">{alert.ilap_score}</Field>
          <Field label="Municipalities">{(alert.municipalities ?? []).join(', ')}</Field>
          <Field label="Sectors impacted">{(alert.sectors_impacted ?? []).join(', ')}</Field>
          <Field label="Operator">{alert.operator}</Field>
          <Field label="Asset">{alert.asset_name}</Field>
          <Field label="Coordinates">
            {typeof alert.latitude === 'number' && typeof alert.longitude === 'number'
              ? <span className="font-mono text-xs">
                  {alert.latitude.toFixed(4)}, {alert.longitude.toFixed(4)}
                  {alert.coord_confidence ? ` (${alert.coord_confidence})` : ''}
                </span>
              : <span className="text-xs text-slate-500">not geolocated — absent from the map layer</span>}
          </Field>
          <Field label="Source">
            {/^https?:\/\//.test(alert.source_ref || '')
              ? <a href={alert.source_ref} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 break-all text-xs text-sky-400 hover:text-sky-300">
                  <Link2 className="h-3.5 w-3.5 shrink-0" />{alert.source_ref}
                </a>
              : <span className="break-all font-mono text-xs">{alert.source_ref}</span>}
          </Field>
        </dl>

        {covertFlags.length > 0 && (
          <div className="mt-4 border-t border-slate-800 pt-4">
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500">
              <Flag className="h-3.5 w-3.5" /> Structural flags
            </p>
            <div className="flex flex-wrap gap-1.5">
              {covertFlags.map((f) => (
                <Badge key={f} variant="outline" className="border-violet-500/30 bg-violet-500/10 text-[10px] text-violet-300">
                  {f}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {alert.validation_notes && (
          <div className="mt-4 border-t border-slate-800 pt-4">
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500">
              Validation notes (VAL-001..010)
            </p>
            <p className="text-sm leading-relaxed text-slate-300">{alert.validation_notes}</p>
          </div>
        )}
      </div>

      {linkedIds.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400">
            <MapPin className="h-3.5 w-3.5" /> Linked assets ({linkedIds.length})
          </h2>
          <div className="space-y-2">
            {linkedIds.map((aid) => {
              const asset = assets.find((a) => a.asset_id === aid)
              return (
                <Link
                  key={aid}
                  to={assetHref(asset, aid)}
                  className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/50 p-3 transition hover:bg-slate-800/50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-200">{asset?.asset_name || aid}</p>
                    <p className="truncate text-xs text-slate-500">
                      {asset ? `${asset.asset_subtype || asset.asset_type} · ${asset.municipality}` : 'not in the loaded asset page'}
                    </p>
                  </div>
                  {asset?.status && (
                    <Badge variant="outline" className="text-xs capitalize">{asset.status}</Badge>
                  )}
                </Link>
              )
            })}
          </div>
        </div>
      )}

      {edges.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400">
            <Network className="h-3.5 w-3.5" /> Dependency edges ({edges.length})
          </h2>
          <div className="space-y-2">
            {edges.map((e, i) => (
              <div key={e.edge_id || i} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs">
                <div className="font-mono text-slate-300">
                  {e.from_asset_id || e.asset_id || '—'} → {e.to_asset_id || '—'}
                </div>
                {(e.dependency_type || e.relationship || e.notes) && (
                  <div className="mt-1 text-slate-500">
                    {[e.dependency_type || e.relationship, e.notes].filter(Boolean).join(' · ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
