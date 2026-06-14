import { useReviewQueue } from '@/lib/hooks'
import { Badge } from '@/components/ui/badge'
import { tierBadge } from '@/lib/format'
import { severityTone } from '@/lib/aguayluz-format'
import { cn } from '@/lib/utils'
import { AlertTriangle } from 'lucide-react'

// Records pending human adjudication (evidence/confidence/coverage gaps).
export default function ReviewQueue() {
  const { data: queue = [] } = useReviewQueue()

  return (
    <div className="h-full overflow-auto p-2 space-y-1.5">
      <div className="px-1 pb-1 text-xs text-slate-400">{queue.length} records in review</div>
      {queue.map((r, i) => (
        <div key={r.record_ref ?? i} className="rounded-md border border-slate-800 bg-slate-900 p-2.5">
          <div className="flex items-center gap-2 flex-wrap">
            <AlertTriangle className={cn('h-3.5 w-3.5 shrink-0', severityTone(r.severity))} />
            <span className={cn('text-[11px] uppercase tracking-wide', severityTone(r.severity))}>{r.severity}</span>
            {r.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(r.evidence_tier))}>{r.evidence_tier}</Badge>}
            {r.confidence != null && <span className="text-[11px] text-slate-500">conf {r.confidence}</span>}
            <span className="text-[11px] font-mono text-slate-500 ml-auto truncate max-w-[140px]">{r.record_ref}</span>
          </div>
          <p className="text-xs text-slate-300 mt-1">{r.reason}</p>
        </div>
      ))}
      {queue.length === 0 && <p className="text-center text-sm text-slate-500 py-8">Queue empty</p>}
    </div>
  )
}
