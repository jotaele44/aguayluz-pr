import { useState } from 'react'
import { useReviewQueuePaged, useDecision } from '@/lib/hooks'
import { postAiQuery } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { tierBadge, severityTone } from '@/lib/format'
import { cn } from '@/lib/utils'
import { AlertTriangle, Bot, CheckCircle, Download, Loader2, SkipForward, X, ChevronLeft, ChevronRight } from 'lucide-react'
import { downloadCSV } from '@/lib/csv'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { useToast } from '@/components/ui/use-toast'
import PageHeader from '@/components/common/PageHeader'

const SEVERITIES = ['all', 'block', 'warn', 'info']
const TIERS = ['all', 'T1', 'T2', 'T3', 'T4']
const PAGE_SIZE = 25

export default function ReviewPage() {
  const [sev, setSev] = useState('all')
  const [tier, setTier] = useState('all')
  const [offset, setOffset] = useState(0)
  const [suggestions, setSuggestions] = useState({})
  const [suggesting, setSuggesting] = useState({})
  const { toast } = useToast()

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

  return (
    <div className="flex flex-col h-full">
      <PageHeader title="Review Queue" subtitle={`${total.toLocaleString()} items pending review`}>
        <Button size="sm" variant="outline" onClick={() => downloadCSV('review-queue.csv', items, ['record_ref','severity','evidence_tier','confidence','record_type','reason','source_ref'])} className="h-8 border-slate-800 bg-slate-950 px-2 text-xs text-slate-400 hover:text-slate-100" title="Export page as CSV">
          <Download className="h-3.5 w-3.5" />
        </Button>
        <Select value={sev} onValueChange={(v) => { setSev(v); setOffset(0) }}>
          <SelectTrigger className="h-7 w-[110px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{SEVERITIES.map((s) => <SelectItem key={s} value={s} className="text-xs capitalize">{s}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={tier} onValueChange={(v) => { setTier(v); setOffset(0) }}>
          <SelectTrigger className="h-7 w-[90px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{TIERS.map((t) => <SelectItem key={t} value={t} className="text-xs">{t}</SelectItem>)}</SelectContent>
        </Select>
      </PageHeader>

      <div className="flex-1 overflow-auto p-6 space-y-2">
        {isLoading
          ? Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-md" />)
          : items.map((r, i) => (
            <div key={r.record_ref ?? i} className="rounded-lg border border-slate-800 bg-slate-900">
              <div className="p-4 flex items-start gap-4">
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
                    onClick={() => handleAiSuggest(r)}
                    title="Ask AI for a recommendation"
                  >
                    {suggesting[r.record_ref]
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      : <Bot className="h-3.5 w-3.5" />}
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 px-2 text-xs text-emerald-400 border-emerald-800 hover:bg-emerald-950" disabled={isPending} onClick={() => handleDecision(r.record_ref, 'accept')}>
                    <CheckCircle className="h-3.5 w-3.5 mr-1" />Accept
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 px-2 text-xs text-red-400 border-red-900 hover:bg-red-950" disabled={isPending} onClick={() => handleDecision(r.record_ref, 'reject')}>
                    <X className="h-3.5 w-3.5 mr-1" />Reject
                  </Button>
                  <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-slate-500" disabled={isPending} onClick={() => handleDecision(r.record_ref, 'skip')}>
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
            <Button size="sm" variant="outline" aria-label="Previous page" className="h-7" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <Button size="sm" variant="outline" aria-label="Next page" className="h-7" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
