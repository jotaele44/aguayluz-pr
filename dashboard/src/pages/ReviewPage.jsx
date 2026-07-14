import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useReviewQueuePaged, useDecision } from '@/lib/hooks'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { tierBadge, severityTone, SEVERITIES, TIERS } from '@/lib/format'
import { cn } from '@/lib/utils'
import { AlertTriangle, CheckCircle, X, SkipForward, ChevronLeft, ChevronRight } from 'lucide-react'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { useToast } from '@/components/ui/use-toast'
import PageHeader from '@/components/common/PageHeader'

const PAGE_SIZE = 25

// Ignore shortcuts while the operator is typing in a field or menu.
const isTypingTarget = (el) =>
  el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.getAttribute?.('role') === 'combobox' || el.isContentEditable)

// Filters live in the URL so a filtered/paged view is shareable and survives reload.
const cleanParams = (prev, patch) => {
  const next = new URLSearchParams(prev)
  for (const [k, v] of Object.entries(patch)) {
    if (v == null || v === '' || v === 'all' || (k === 'offset' && !Number(v))) next.delete(k)
    else next.set(k, String(v))
  }
  return next
}

export default function ReviewPage() {
  const [params, setParams] = useSearchParams()
  const sev = params.get('sev') || 'all'
  const tier = params.get('tier') || 'all'
  const offset = Number(params.get('offset')) || 0
  const setFilter = (patch) => setParams((p) => cleanParams(p, patch), { replace: true })

  const [cursor, setCursor] = useState(0)
  const { toast } = useToast()
  const rowRefs = useRef([])

  const { data, isLoading } = useReviewQueuePaged({
    severity: sev === 'all' ? undefined : sev,
    tier: tier === 'all' ? undefined : tier,
    offset,
    limit: PAGE_SIZE,
  })
  const { mutate: decide, isPending } = useDecision()

  const items = data?.items ?? []
  const total = data?.total ?? 0

  const handleDecision = (ref, decision) => {
    if (!ref) return
    decide({ ref, decision }, {
      onSuccess: () => toast({ title: `Marked ${decision}`, description: ref }),
      onError: () => toast({ variant: 'destructive', title: 'Decision failed' }),
    })
  }

  // Keep the keyboard cursor within the current page as items shrink/refetch.
  useEffect(() => {
    setCursor((c) => Math.min(c, Math.max(0, items.length - 1)))
  }, [items.length])

  // Keyboard triage: J/K (or arrows) to move, A/R/S to accept/reject/skip.
  useEffect(() => {
    const onKey = (e) => {
      if (isTypingTarget(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      const k = e.key.toLowerCase()
      if (k === 'j' || e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, items.length - 1)) }
      else if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
      else if (k === 'a' || k === 'r' || k === 's') {
        const row = items[cursor]
        if (!row) return
        e.preventDefault()
        handleDecision(row.record_ref, k === 'a' ? 'accept' : k === 'r' ? 'reject' : 'skip')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items, cursor])

  useEffect(() => {
    rowRefs.current[cursor]?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  return (
    <div className="flex flex-col h-full">
      <PageHeader title="Review Queue" subtitle={`${total.toLocaleString()} pending · J/K move · A accept · R reject · S skip`}>
        <Select value={sev} onValueChange={(v) => setFilter({ sev: v, offset: 0 })}>
          <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{SEVERITIES.map((s) => <SelectItem key={s} value={s} className="text-xs capitalize">{s}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={tier} onValueChange={(v) => setFilter({ tier: v, offset: 0 })}>
          <SelectTrigger className="h-7 w-[90px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{TIERS.map((t) => <SelectItem key={t} value={t} className="text-xs">{t}</SelectItem>)}</SelectContent>
        </Select>
      </PageHeader>

      <div className="flex-1 overflow-auto p-6 space-y-2">
        {isLoading
          ? Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-md" />)
          : items.map((r, i) => (
            <div
              key={r.record_ref ?? i}
              ref={(el) => { rowRefs.current[i] = el }}
              onClick={() => setCursor(i)}
              className={cn(
                'rounded-lg border bg-slate-900 p-4 flex items-start gap-4',
                i === cursor ? 'border-sky-500/50 ring-1 ring-inset ring-sky-500/30' : 'border-slate-800',
              )}
            >
              <AlertTriangle className={cn('h-4 w-4 shrink-0 mt-0.5', severityTone(r.severity))} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className={cn('text-xs uppercase tracking-wide font-semibold', severityTone(r.severity))}>{r.severity}</span>
                  {r.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(r.evidence_tier))}>{r.evidence_tier}</Badge>}
                  {r.confidence != null && <span className="text-[11px] text-slate-500">conf {r.confidence}</span>}
                  <span className="text-[11px] font-mono text-slate-500 ml-auto truncate max-w-[200px]">{r.record_ref}</span>
                </div>
                <p className="text-sm text-slate-300">{r.reason}</p>
              </div>
              <div className="flex gap-1.5 shrink-0">
                <Button size="sm" variant="outline" className="h-7 px-2 text-xs text-emerald-400 border-emerald-800 hover:bg-emerald-950" disabled={isPending} onClick={() => handleDecision(r.record_ref, 'accept')}>
                  <CheckCircle className="h-3.5 w-3.5 mr-1" />Accept
                </Button>
                <Button size="sm" variant="outline" className="h-7 px-2 text-xs text-red-400 border-red-900 hover:bg-red-950" disabled={isPending} onClick={() => handleDecision(r.record_ref, 'reject')}>
                  <X className="h-3.5 w-3.5 mr-1" />Reject
                </Button>
                <Button size="sm" variant="ghost" aria-label="Skip" title="Skip" className="h-7 px-2 text-xs text-slate-500" disabled={isPending} onClick={() => handleDecision(r.record_ref, 'skip')}>
                  <SkipForward className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        {!isLoading && items.length === 0 && (
          <p className="text-center text-sm text-slate-500 py-16">No items match filters</p>
        )}
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between px-6 py-3 border-t border-slate-800 shrink-0">
          <span className="text-xs text-slate-500">{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" aria-label="Previous page" className="h-7" disabled={offset === 0} onClick={() => setFilter({ offset: Math.max(0, offset - PAGE_SIZE) })}>
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <Button size="sm" variant="outline" aria-label="Next page" className="h-7" disabled={offset + PAGE_SIZE >= total} onClick={() => setFilter({ offset: offset + PAGE_SIZE })}>
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
