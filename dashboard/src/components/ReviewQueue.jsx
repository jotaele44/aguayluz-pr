import { useMemo, useState } from 'react'
import { useReviewQueue } from '@/lib/hooks'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { SEVERITIES, TIERS } from '@/lib/format'
import { AlertTriangle, Search } from 'lucide-react'
import ReviewRecordCard from '@/components/ReviewRecordCard'

const SEVERITY_RANK = { block: 0, warn: 1, info: 2 }

function normalized(value) {
  return `${value ?? ''}`.toLowerCase()
}

export default function ReviewQueue() {
  const { data: queue = [], isLoading } = useReviewQueue()
  const [q, setQ] = useState('')
  const [sev, setSev] = useState('all')
  const [tier, setTier] = useState('all')

  const rows = useMemo(() => [...queue]
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9) || normalized(a.record_ref).localeCompare(normalized(b.record_ref)))
    .filter((r) => {
      const haystack = [r.record_ref, r.reason, r.severity, r.evidence_tier, r.source_ref, r.record_type]
        .map(normalized).join(' ')
      return (
        (sev === 'all' || r.severity === sev) &&
        (tier === 'all' || r.evidence_tier === tier) &&
        (!q || haystack.includes(normalized(q)))
      )
    }), [queue, q, sev, tier])

  if (isLoading) {
    return (
      <div className="h-full p-2 space-y-1.5">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded-md" />
        ))}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-slate-900 px-2 pb-2">
        <div className="rounded-md border border-amber-500/20 bg-amber-500/10 p-2 text-[11px] leading-relaxed text-amber-200/90">
          Review queue is read-only in this panel. Use the Review page for approve/reject/skip actions.
        </div>
        <div className="flex items-center gap-2">
          <div className="flex w-10 shrink-0 items-center gap-1 text-xs text-slate-400"><AlertTriangle className="h-3.5 w-3.5 text-amber-300" />{rows.length}</div>
          <Select value={sev} onValueChange={setSev}>
            <SelectTrigger className="h-7 w-[90px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{SEVERITIES.map((s) => <SelectItem key={s} value={s} className="text-xs capitalize">{s}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={tier} onValueChange={setTier}>
            <SelectTrigger className="h-7 w-[75px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{TIERS.map((t) => <SelectItem key={t} value={t} className="text-xs">{t}</SelectItem>)}</SelectContent>
          </Select>
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-slate-500" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search reason/source…" className="h-8 border-slate-800 bg-slate-950 pl-7 text-xs" />
          </div>
        </div>
      </div>

      <div className="h-full overflow-auto p-2 space-y-1.5">
        {rows.map((r, i) => (
          <ReviewRecordCard
            key={r.record_ref ?? i}
            record={r}
            compact
            footer={(r.record_type || r.source_ref) && (
              <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
                {r.record_type && <span>type: {r.record_type}</span>}
                {r.source_ref && <span className="truncate">source: {r.source_ref}</span>}
              </div>
            )}
          />
        ))}
        {rows.length === 0 && <p className="py-8 text-center text-sm text-slate-500">No review records match the active filters.</p>}
      </div>
    </div>
  )
}
