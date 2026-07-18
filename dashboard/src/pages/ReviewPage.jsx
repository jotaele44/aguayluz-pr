import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useReviewQueuePaged, useDecision } from '@/lib/hooks'
import { postAiQuery } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { tierBadge, severityTone, SEVERITIES, TIERS } from '@/lib/format'
import { cn } from '@/lib/utils'
import { AlertTriangle, Bot, CheckCircle, Download, Loader2, SkipForward, X, ChevronLeft, ChevronRight, CheckSquare, Square } from 'lucide-react'
import { downloadCSV } from '@/lib/csv'
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
  const [suggestions, setSuggestions] = useState({})
  const [suggesting, setSuggesting] = useState({})
  const [selected, setSelected] = useState(new Set())
  const [batchPending, setBatchPending] = useState(false)
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

  const handleAiSuggest = async (item) => {
    const ref = item.record_ref
    setSuggesting((s) => ({ ...s, [ref]: true }))
    const result = await postAiQuery(
      `Review queue item for Puerto Rico infrastructure data: ` +
      `record_ref=${ref}, type=${item.record_type ?? 'unknown'}, ` +
      `severity=${item.severity}, evidence_tier=${item.evidence_tier ?? 'unknown'}, ` +
      `confidence=${item.confidence ?? 'unknown'}. ` +
      `Reason: ${item.reason ?? 'no reason provided'}. ` +
      `Should this record be accepted (data is valid), rejected (data is incorrect/duplicate), ` +
      `or skipped (needs more context)? Respond in one concise sentence with your recommendation.`
    )
    setSuggestions((s) => ({ ...s, [ref]: result?.answer ?? result?.error ?? 'No response' }))
    setSuggesting((s) => ({ ...s, [ref]: false }))
  }

  const allSelected = items.length > 0 && items.every((r) => selected.has(r.record_ref))
  const someSelected = items.some((r) => selected.has(r.record_ref))

  const toggleAll = () => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (allSelected) items.forEach((r) => next.delete(r.record_ref))
      else items.forEach((r) => next.add(r.record_ref))
      return next
    })
  }

  const toggleOne = (ref) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(ref) ? next.delete(ref) : next.add(ref)
      return next
    })
  }

  const handleBatchDecision = async (decision) => {
    const refs = items.filter((r) => selected.has(r.record_ref)).map((r) => r.record_ref)
    if (!refs.length) return
    setBatchPending(true)
    for (const ref of refs) {
      await new Promise((resolve) => decide({ ref, decision }, { onSuccess: resolve, onError: resolve }))
    }
    setSelected(new Set())
    setBatchPending(false)
    toast({ title: `Batch ${decision}`, description: `${refs.length} items processed` })
  }

  const selCount = items.filter((r) => selected.has(r.record_ref)).length

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
        {someSelected && (
          <>
            <span className="text-xs text-slate-400">{selCount} selected</span>
            <Button size="sm" variant="outline" className="h-7 px-2 text-xs text-emerald-400 border-emerald-800 hover:bg-emerald-950" disabled={batchPending} onClick={() => handleBatchDecision('accept')}>
              {batchPending ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <CheckCircle className="h-3.5 w-3.5 mr-1" />}
              Approve all
            </Button>
            <Button size="sm" variant="outline" className="h-7 px-2 text-xs text-red-400 border-red-900 hover:bg-red-950" disabled={batchPending} onClick={() => handleBatchDecision('reject')}>
              {batchPending ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <X className="h-3.5 w-3.5 mr-1" />}
              Reject all
            </Button>
            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-slate-500" disabled={batchPending} onClick={() => handleBatchDecision('skip')}>
              Skip all
            </Button>
          </>
        )}
        <Button size="sm" variant="outline" onClick={() => downloadCSV('review-queue.csv', items, ['record_ref','severity','evidence_tier','confidence','record_type','reason','source_ref'])} className="h-8 border-slate-800 bg-slate-950 px-2 text-xs text-slate-400 hover:text-slate-100" title="Export page as CSV">
          <Download className="h-3.5 w-3.5" />
        </Button>
        <Select value={sev} onValueChange={(v) => setFilter({ sev: v, offset: 0 })}>
          <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{SEVERITIES.map((s) => <SelectItem key={s} value={s} className="text-xs capitalize">{s}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={tier} onValueChange={(v) => setFilter({ tier: v, offset: 0 })}>
          <SelectTrigger className="h-7 w-[90px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{TIERS.map((t) => <SelectItem key={t} value={t} className="text-xs">{t}</SelectItem>)}</SelectContent>
        </Select>
      </PageHeader>

      {items.length > 0 && (
        <div className="flex items-center gap-2 px-6 py-2 border-b border-slate-800/60 bg-slate-900/40 shrink-0">
          <button onClick={toggleAll} className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200">
            {allSelected
              ? <CheckSquare className="h-4 w-4 text-sky-400" />
              : someSelected
                ? <CheckSquare className="h-4 w-4 text-slate-500" />
                : <Square className="h-4 w-4" />}
            {allSelected ? 'Deselect all' : 'Select all on page'}
          </button>
        </div>
      )}

      <div className="flex-1 overflow-auto p-6 space-y-2">
        {isLoading
          ? Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-md" />)
          : items.map((r, i) => (
            <div
              key={r.record_ref ?? i}
              ref={(el) => { rowRefs.current[i] = el }}
              onClick={() => setCursor(i)}
              className={cn(
                'rounded-lg border bg-slate-900',
                i === cursor
                  ? 'border-sky-500/50 ring-1 ring-inset ring-sky-500/30'
                  : selected.has(r.record_ref) ? 'border-sky-600/50 bg-sky-950/20' : 'border-slate-800',
              )}
            >
              <div className="p-4 flex items-start gap-3">
                <button
                  onClick={(e) => { e.stopPropagation(); toggleOne(r.record_ref) }}
                  aria-label={selected.has(r.record_ref) ? 'Deselect record' : 'Select record'}
                  className="mt-0.5 shrink-0 text-slate-500 hover:text-sky-400"
                >
                  {selected.has(r.record_ref)
                    ? <CheckSquare className="h-4 w-4 text-sky-400" />
                    : <Square className="h-4 w-4" />}
                </button>
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
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs text-sky-400 border-sky-900 hover:bg-sky-950"
                    disabled={suggesting[r.record_ref]}
                    onClick={(e) => { e.stopPropagation(); handleAiSuggest(r) }}
                    title="Ask AI for a recommendation"
                  >
                    {suggesting[r.record_ref]
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <Bot className="h-3.5 w-3.5" />}
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 px-2 text-xs text-emerald-400 border-emerald-800 hover:bg-emerald-950" disabled={isPending} onClick={(e) => { e.stopPropagation(); handleDecision(r.record_ref, 'accept') }}>
                    <CheckCircle className="h-3.5 w-3.5 mr-1" />Accept
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 px-2 text-xs text-red-400 border-red-900 hover:bg-red-950" disabled={isPending} onClick={(e) => { e.stopPropagation(); handleDecision(r.record_ref, 'reject') }}>
                    <X className="h-3.5 w-3.5 mr-1" />Reject
                  </Button>
                  <Button size="sm" variant="ghost" aria-label="Skip" title="Skip" className="h-7 px-2 text-xs text-slate-500" disabled={isPending} onClick={(e) => { e.stopPropagation(); handleDecision(r.record_ref, 'skip') }}>
                    <SkipForward className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
              {suggestions[r.record_ref] && (
                <div className="border-t border-sky-900/30 bg-sky-950/20 px-4 py-2.5 flex items-start gap-2 rounded-b-lg">
                  <Bot className="h-3.5 w-3.5 text-sky-400 shrink-0 mt-0.5" />
                  <p className="text-xs text-sky-200 leading-relaxed">{suggestions[r.record_ref]}</p>
                </div>
              )}
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
