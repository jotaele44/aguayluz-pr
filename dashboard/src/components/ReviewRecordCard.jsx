import { Badge } from '@/components/ui/badge'
import { AlertTriangle } from 'lucide-react'
import { tierBadge, severityTone } from '@/lib/format'
import { cn } from '@/lib/utils'

// One review-queue record, shared by the full Review page and the compact
// map-rail panel. `compact` tightens spacing for the narrow rail; `actions`
// renders adjudication controls (omit → read-only); `footer` renders extra
// chips; `active`/`onClick`/`innerRef` support the Review page's keyboard cursor.
export default function ReviewRecordCard({ record: r, compact = false, actions, footer, active, onClick, innerRef }) {
  return (
    <div
      ref={innerRef}
      onClick={onClick}
      className={cn(
        'flex items-start rounded-lg border bg-slate-900',
        compact ? 'gap-3 p-2.5' : 'gap-4 p-4',
        active ? 'border-sky-500/50 ring-1 ring-inset ring-sky-500/30' : 'border-slate-800',
        onClick && 'cursor-pointer',
      )}
    >
      <AlertTriangle className={cn('shrink-0', compact ? 'h-3.5 w-3.5' : 'mt-0.5 h-4 w-4', severityTone(r.severity))} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <span className={cn('font-semibold uppercase tracking-wide', compact ? 'text-[11px]' : 'text-xs', severityTone(r.severity))}>
            {r.severity || 'review'}
          </span>
          {r.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(r.evidence_tier))}>{r.evidence_tier}</Badge>}
          {r.confidence != null && <span className="text-[11px] text-slate-500">conf {r.confidence}</span>}
          <span className={cn('ml-auto truncate font-mono text-[11px] text-slate-500', compact ? 'max-w-[150px]' : 'max-w-[200px]')}>
            {r.record_ref}
          </span>
        </div>
        <p className={cn('text-slate-300', compact ? 'text-xs leading-relaxed' : 'text-sm')}>{r.reason || 'No review reason provided.'}</p>
        {footer}
      </div>
      {actions}
    </div>
  )
}
