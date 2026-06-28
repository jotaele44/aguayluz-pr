import { useMemo, useState } from 'react'
import { useReviewQueue } from '@/lib/hooks'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { tierBadge } from '@/lib/format'
import { severityTone } from '@/lib/aguayluz-format'
import { cn } from '@/lib/utils'
import { AlertTriangle, Search } from 'lucide-react'

const SEVERITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 }

function normalized(value) {
  return `${value ?? ''}`.toLowerCase()
}

export default function ReviewQueue() {
  const { data: queue = [] } = useReviewQueue()
  const [q, setQ] = useState('')

  const rows = useMemo(() => [...queue]
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9) || normalized(a.record_ref).localeCompare(normalized(b.record_ref)))
    .filter((r) => {
      const haystack = [r.record_ref, r.reason, r.severity, r.evidence_tier, r.source_ref, r.record_type]
        .map(normalized)
        .join(' ')
      return !q || haystack.includes(normalized(q))
    }), [queue, q])

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-slate-900 px-2 pb-2">
        <div className="rounded-md border border-amber-500/20 bg-amber-500/10 p-2 text-[11px] leading-relaxed text-amber-200/90">
          Review queue is read-only in this dashboard. Promotion/adjudication remains a controlled repo workflow.
        </div>
        <div className="flex items-center gap-2">
          <div className="flex w-12 shrink-0 items-center gap-1 text-xs text-slate-400"><AlertTriangle className="h-3.5 w-3.5 text-amber-300" />{rows.length}</div>
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-slate-500" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search review reason/source…" className="h-8 border-slate-800 bg-slate-950 pl-7 text-xs" />
          </div>
        </div>
      </div>

      <div className="h-full overflow-auto p-2 space-y-1.5">
        {rows.map((r, i) => (
          <div key={r.record_ref ?? i} className="rounded-md border border-slate-800 bg-slate-900 p-2.5">
            <div className="flex items-center gap-2 flex-wrap">
              <AlertTriangle className={cn('h-3.5 w-3.5 shrink-0', severityTone(r.severity))} />
              <span className={cn('text-[11px] uppercase tracking-wide', severityTone(r.severity))}>{r.severity || 'review'}</span>
              {r.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(r.evidence_tier))}>{r.evidence_tier}</Badge>}
              {r.confidence != null && <span className="text-[11px] text-slate-500">conf {r.confidence}</span>}
              <span className="ml-auto max-w-[150px] truncate font-mono text-[11px] text-slate-500">{r.record_ref}</span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">{r.reason || 'No review reason provided.'}</p>
            <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
              {r.record_type && <span>type: {r.record_type}</span>}
              {r.source_ref && <span className="truncate">source: {r.source_ref}</span>}
            </div>
          </div>
        ))}
        {rows.length === 0 && <p className="py-8 text-center text-sm text-slate-500">No review records match the active search.</p>}
      </div>
    </div>
  )
}
