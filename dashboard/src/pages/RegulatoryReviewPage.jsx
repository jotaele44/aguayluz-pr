import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle, Hash, ShieldAlert, XCircle } from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { useToast } from '@/components/ui/use-toast'
import {
  getRegulatoryLink,
  getRegulatoryLinks,
  postRegulatoryLinkDecision,
} from '@/lib/regulatory-api'
import { cn } from '@/lib/utils'

const titleCase = (value) => String(value || 'unknown')
  .replaceAll('_', ' ')
  .replace(/\b\w/g, (letter) => letter.toUpperCase())

const formatDate = (value) => {
  if (!value) return 'Unknown'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

const DECISION_STATES = ['all', 'proposed', 'needs_review', 'approved', 'rejected']

function DecisionBadge({ state }) {
  const normalized = state || 'proposed'
  return (
    <span className={cn(
      'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold',
      normalized === 'approved' && 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
      normalized === 'rejected' && 'border-red-500/40 bg-red-500/10 text-red-300',
      normalized === 'needs_review' && 'border-amber-500/40 bg-amber-500/10 text-amber-300',
      normalized === 'proposed' && 'border-slate-600 bg-slate-800 text-slate-300',
    )}>
      {titleCase(normalized)}
    </span>
  )
}

function LoadingBlock({ label }) {
  return (
    <div role="status" className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 text-sm text-slate-400">
      Loading {label}…
    </div>
  )
}

export default function RegulatoryReviewPage() {
  const [decisionState, setDecisionState] = useState('proposed')
  const [selectedId, setSelectedId] = useState(null)
  const [actor, setActor] = useState('')
  const [rationale, setRationale] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const linksQuery = useQuery({
    queryKey: ['regulatory', 'links', decisionState],
    queryFn: () => getRegulatoryLinks({
      decision_state: decisionState === 'all' ? undefined : decisionState,
      limit: 200,
    }),
  })

  const candidates = linksQuery.data?.items ?? []
  useEffect(() => {
    if (candidates.length && !candidates.some((c) => c.candidate_id === selectedId)) {
      setSelectedId(candidates[0].candidate_id)
    }
    if (!candidates.length) setSelectedId(null)
  }, [candidates, selectedId])

  const detailQuery = useQuery({
    queryKey: ['regulatory', 'link', selectedId],
    queryFn: () => getRegulatoryLink(selectedId),
    enabled: Boolean(selectedId),
  })
  const detail = detailQuery.data

  const hasContradictions = (detail?.contradictions?.length ?? 0) > 0
  const canSubmit = actor.trim().length > 0 && rationale.trim().length > 0 && !submitting

  const submitDecision = async (targetState) => {
    if (!selectedId || !canSubmit) return
    setSubmitting(true)
    try {
      await postRegulatoryLinkDecision(selectedId, targetState, actor.trim(), rationale.trim())
      toast({ title: `Marked ${titleCase(targetState)}`, description: selectedId })
      setRationale('')
      await queryClient.invalidateQueries({ queryKey: ['regulatory', 'links'] })
      await queryClient.invalidateQueries({ queryKey: ['regulatory', 'link', selectedId] })
    } catch (err) {
      toast({ variant: 'destructive', title: 'Decision failed', description: err.message })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Regulatory Link Review"
        subtitle="Adjudicate candidate links between provider observations and AguaLuz assets"
      />
      <div className="flex-1 min-h-0 overflow-auto p-6">
        <ErrorBoundary label="Regulatory link review">
          <div
            role="note"
            aria-label="Adjudication scope limitation"
            className="mb-5 flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4"
          >
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
            <div>
              <div className="font-semibold text-amber-200">Fail-closed approval</div>
              <p className="mt-1 text-sm text-amber-100/80">
                A candidate with open contradictions cannot be approved through this workflow. Approving
                requires an actor and a rationale, both recorded permanently on the decision.
              </p>
            </div>
          </div>

          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Select value={decisionState} onValueChange={setDecisionState}>
              <SelectTrigger aria-label="Filter by decision state" className="h-8 w-[170px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {DECISION_STATES.map((s) => (
                  <SelectItem key={s} value={s} className="text-xs capitalize">{s === 'all' ? 'All decision states' : titleCase(s)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-xs text-slate-500">{candidates.length} of {linksQuery.data?.total ?? 0} shown</span>
          </div>

          {linksQuery.isLoading ? (
            <LoadingBlock label="candidate links" />
          ) : linksQuery.isError ? (
            <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
              The regulatory link API is unavailable.
            </div>
          ) : (
            <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
              <section aria-labelledby="link-queue">
                <h2 id="link-queue" className="sr-only">Candidate queue</h2>
                {candidates.length === 0 ? (
                  <p className="text-sm text-slate-400">No candidates match the current filter.</p>
                ) : (
                  <div className="space-y-2">
                    {candidates.map((c) => (
                      <button
                        key={c.candidate_id}
                        type="button"
                        aria-pressed={selectedId === c.candidate_id}
                        onClick={() => setSelectedId(c.candidate_id)}
                        className={cn(
                          'w-full rounded-lg border p-3 text-left transition-colors',
                          selectedId === c.candidate_id
                            ? 'border-sky-500/50 bg-sky-500/10'
                            : 'border-slate-800 bg-slate-900/60 hover:border-slate-700 hover:bg-slate-900',
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-slate-100">{c.candidate_asset_id}</div>
                            <div className="mt-1 text-xs text-slate-500">{titleCase(c.match_strength)}</div>
                          </div>
                          <DecisionBadge state={c.decision_state} />
                        </div>
                        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                          <span>{c.contradictions?.length ?? 0} contradiction(s)</span>
                          <span>{formatDate(c.created_at)}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </section>

              <section aria-labelledby="link-detail" className="min-w-0">
                <h2 id="link-detail" className="sr-only">Selected candidate detail</h2>
                {!selectedId || detailQuery.isLoading ? (
                  <LoadingBlock label="candidate detail" />
                ) : !detail ? (
                  <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
                    The selected candidate detail could not be loaded.
                  </div>
                ) : (
                  <div className="space-y-5">
                    <article className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-xs uppercase tracking-wide text-slate-500">{detail.candidate_id}</p>
                          <h3 className="mt-1 text-xl font-semibold text-slate-100">{detail.candidate_asset_id}</h3>
                          <p className="mt-1 text-sm text-slate-400">
                            Observation: {detail.observation?.provider} · {detail.observation?.provider_record_id}
                          </p>
                        </div>
                        <DecisionBadge state={detail.decision_state} />
                      </div>

                      {detail.decided_by && (
                        <p className="mt-3 text-xs text-slate-500">
                          Decided by {detail.decided_by} on {formatDate(detail.decided_at)} — {detail.decision_rationale}
                        </p>
                      )}
                    </article>

                    <section aria-labelledby="match-features" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                      <h3 id="match-features" className="flex items-center gap-2 font-semibold text-slate-100">
                        <Hash className="h-4 w-4 text-sky-400" aria-hidden="true" /> Match evidence
                      </h3>
                      <p className="mt-1 text-xs text-slate-500">Match strength: {titleCase(detail.match_strength)}</p>
                      <ul className="mt-3 space-y-2">
                        {(detail.match_features ?? []).map((f, i) => (
                          <li key={`${f.feature}-${i}`} className="rounded-md border border-slate-800 bg-slate-950/40 p-3 text-sm">
                            <span className="text-slate-500">{titleCase(f.feature)}:</span>{' '}
                            <span className="text-slate-200">{f.value}</span>
                          </li>
                        ))}
                      </ul>
                    </section>

                    <section aria-labelledby="contradictions" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                      <h3 id="contradictions" className="flex items-center gap-2 font-semibold text-slate-100">
                        <ShieldAlert className="h-4 w-4 text-amber-400" aria-hidden="true" /> Contradictions
                      </h3>
                      {hasContradictions ? (
                        <ul className="mt-3 space-y-2">
                          {detail.contradictions.map((c, i) => (
                            <li key={i} className="rounded-md border border-red-500/20 bg-red-500/5 p-3 text-sm text-red-100">
                              <span className="font-medium">{titleCase(c.kind)}:</span> {c.detail}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-2 text-sm text-slate-400">No contradictions recorded — approval is not blocked.</p>
                      )}
                    </section>

                    <section aria-labelledby="decision-form" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                      <h3 id="decision-form" className="font-semibold text-slate-100">Record a decision</h3>
                      <div className="mt-3 space-y-3">
                        <div>
                          <label htmlFor="actor-input" className="text-[11px] uppercase tracking-wide text-slate-500">Actor</label>
                          <input
                            id="actor-input"
                            type="text"
                            value={actor}
                            onChange={(e) => setActor(e.target.value)}
                            placeholder="Your name or identifier"
                            className="mt-1 flex h-9 w-full rounded-md border border-slate-800 bg-slate-950/60 px-3 py-1 text-sm text-slate-200 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sky-500"
                          />
                        </div>
                        <div>
                          <label htmlFor="rationale-input" className="text-[11px] uppercase tracking-wide text-slate-500">Rationale</label>
                          <textarea
                            id="rationale-input"
                            value={rationale}
                            onChange={(e) => setRationale(e.target.value)}
                            rows={3}
                            placeholder="Why this decision is correct"
                            className="mt-1 flex w-full rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sky-500"
                          />
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            type="button"
                            disabled={!canSubmit || hasContradictions}
                            title={hasContradictions ? 'Cannot approve while contradictions remain open' : undefined}
                            onClick={() => submitDecision('approved')}
                            className="gap-1.5"
                          >
                            <CheckCircle className="h-4 w-4" /> Approve
                          </Button>
                          <Button
                            type="button"
                            variant="destructive"
                            disabled={!canSubmit}
                            onClick={() => submitDecision('rejected')}
                            className="gap-1.5"
                          >
                            <XCircle className="h-4 w-4" /> Reject
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            disabled={!canSubmit}
                            onClick={() => submitDecision('needs_review')}
                          >
                            Mark needs review
                          </Button>
                        </div>
                      </div>
                    </section>
                  </div>
                )}
              </section>
            </div>
          )}
        </ErrorBoundary>
      </div>
    </div>
  )
}
