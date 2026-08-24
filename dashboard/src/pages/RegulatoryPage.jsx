import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Database,
  FileText,
  Hash,
  Landmark,
  ShieldAlert,
} from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import {
  getRegulatoryObservation,
  getRegulatoryObservations,
  getRegulatorySummary,
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

const PROVIDERS = ['all', 'EPA', 'FDA', 'USGS', 'DRNA', 'PRASA_AAA', 'PREQB']
const RECORD_FAMILIES = ['all', 'entity', 'permit', 'inspection', 'enforcement']
const FRESHNESS_STATES = ['all', 'current', 'historical', 'stale', 'unknown', 'conflicting']

function FreshnessBadge({ state }) {
  const normalized = state || 'unknown'
  return (
    <span className={cn(
      'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold',
      normalized === 'current' && 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
      normalized === 'historical' && 'border-slate-600 bg-slate-800 text-slate-300',
      normalized === 'stale' && 'border-amber-500/40 bg-amber-500/10 text-amber-300',
      normalized === 'conflicting' && 'border-red-500/40 bg-red-500/10 text-red-300',
      normalized === 'unknown' && 'border-slate-600 bg-slate-800 text-slate-300',
    )}>
      {titleCase(normalized)}
    </span>
  )
}

function MetricCard({ label, value, detail, icon: Icon }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
        <Icon className="h-4 w-4" aria-hidden="true" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
      {detail && <div className="mt-1 text-xs text-slate-500">{detail}</div>}
    </div>
  )
}

function DetailList({ items }) {
  return (
    <dl className="grid gap-3 sm:grid-cols-2">
      {items.map(({ term, value }) => (
        <div key={term} className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
          <dt className="text-[11px] uppercase tracking-wide text-slate-500">{term}</dt>
          <dd className="mt-1 text-sm text-slate-200 break-words">{value || 'Unknown'}</dd>
        </div>
      ))}
    </dl>
  )
}

function LoadingBlock({ label }) {
  return (
    <div role="status" className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 text-sm text-slate-400">
      Loading {label}…
    </div>
  )
}

export default function RegulatoryPage() {
  const [provider, setProvider] = useState('all')
  const [recordFamily, setRecordFamily] = useState('all')
  const [freshnessState, setFreshnessState] = useState('all')
  const [selectedId, setSelectedId] = useState(null)

  const summaryQuery = useQuery({
    queryKey: ['regulatory', 'summary'],
    queryFn: getRegulatorySummary,
  })
  const observationsQuery = useQuery({
    queryKey: ['regulatory', 'observations', provider, recordFamily, freshnessState],
    queryFn: () => getRegulatoryObservations({
      provider: provider === 'all' ? undefined : provider,
      record_family: recordFamily === 'all' ? undefined : recordFamily,
      freshness_state: freshnessState === 'all' ? undefined : freshnessState,
      limit: 200,
    }),
  })

  const observations = observationsQuery.data?.items ?? []
  useEffect(() => {
    if (observations.length && !observations.some((o) => o.observation_id === selectedId)) {
      setSelectedId(observations[0].observation_id)
    }
    if (!observations.length) setSelectedId(null)
  }, [observations, selectedId])

  const detailQuery = useQuery({
    queryKey: ['regulatory', 'observation', selectedId],
    queryFn: () => getRegulatoryObservation(selectedId),
    enabled: Boolean(selectedId),
  })

  const summary = summaryQuery.data
  const detail = detailQuery.data
  const queryFailed = summaryQuery.isError || observationsQuery.isError || !summary

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Regulatory Observations"
        subtitle="Read-only provider observations — no entity linkage or facility identity is asserted"
      />
      <div className="flex-1 min-h-0 overflow-auto p-6">
        <ErrorBoundary label="Regulatory observations">
          <div
            role="note"
            aria-label="Regulatory framework scope limitation"
            className="mb-5 flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4"
          >
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
            <div>
              <div className="font-semibold text-amber-200">Non-authoritative, no entity linkage yet</div>
              <p className="mt-1 text-sm text-amber-100/80">
                {summary?.scope?.statement
                  ?? 'Live provider observations only. An observation is a source\'s own statement, never a claim about which AguaLuz facility it describes.'}
              </p>
            </div>
          </div>

          {summaryQuery.isLoading || observationsQuery.isLoading ? (
            <LoadingBlock label="regulatory observations" />
          ) : queryFailed ? (
            <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
              The regulatory observations API is unavailable. No provider data is inferred.
            </div>
          ) : (
            <>
              <section aria-labelledby="regulatory-overview" className="mb-6">
                <h2 id="regulatory-overview" className="sr-only">Observation counts</h2>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <MetricCard
                    icon={Database}
                    label="Observations"
                    value={summary.counts.observations}
                    detail={`${summary.counts.receipts} source receipts`}
                  />
                  <MetricCard
                    icon={Landmark}
                    label="Providers"
                    value={Object.keys(summary.provider).length}
                    detail={Object.keys(summary.provider).join(', ') || 'None yet'}
                  />
                  <MetricCard
                    icon={ShieldAlert}
                    label="Stale / conflicting"
                    value={(summary.freshness_state.stale ?? 0) + (summary.freshness_state.conflicting ?? 0)}
                    detail={`${summary.freshness_state.current ?? 0} current`}
                  />
                  <MetricCard
                    icon={FileText}
                    label="Record families"
                    value={Object.keys(summary.record_family).length}
                    detail={Object.keys(summary.record_family).join(', ') || 'None yet'}
                  />
                </div>
              </section>

              <div className="mb-4 flex flex-wrap items-center gap-2">
                <Select value={provider} onValueChange={setProvider}>
                  <SelectTrigger aria-label="Filter by provider" className="h-8 w-[140px] text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PROVIDERS.map((p) => (
                      <SelectItem key={p} value={p} className="text-xs">{p === 'all' ? 'All providers' : p}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={recordFamily} onValueChange={setRecordFamily}>
                  <SelectTrigger aria-label="Filter by record family" className="h-8 w-[160px] text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {RECORD_FAMILIES.map((f) => (
                      <SelectItem key={f} value={f} className="text-xs capitalize">{f === 'all' ? 'All record families' : f}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={freshnessState} onValueChange={setFreshnessState}>
                  <SelectTrigger aria-label="Filter by freshness state" className="h-8 w-[160px] text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {FRESHNESS_STATES.map((f) => (
                      <SelectItem key={f} value={f} className="text-xs capitalize">{f === 'all' ? 'All freshness states' : f}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-xs text-slate-500">{observations.length} of {observationsQuery.data?.total ?? 0} shown</span>
              </div>

              <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
                <section aria-labelledby="regulatory-list">
                  <h2 id="regulatory-list" className="sr-only">Observation list</h2>
                  {observations.length === 0 ? (
                    <p className="text-sm text-slate-400">No observations match the current filters.</p>
                  ) : (
                    <div className="space-y-2">
                      {observations.map((obs) => (
                        <button
                          key={obs.observation_id}
                          type="button"
                          aria-pressed={selectedId === obs.observation_id}
                          onClick={() => setSelectedId(obs.observation_id)}
                          className={cn(
                            'w-full rounded-lg border p-3 text-left transition-colors',
                            selectedId === obs.observation_id
                              ? 'border-sky-500/50 bg-sky-500/10'
                              : 'border-slate-800 bg-slate-900/60 hover:border-slate-700 hover:bg-slate-900',
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="truncate text-sm font-medium text-slate-100">{obs.provider} · {obs.provider_record_id}</div>
                              <div className="mt-1 text-xs text-slate-500">{titleCase(obs.record_family)}</div>
                            </div>
                            <FreshnessBadge state={obs.freshness_state} />
                          </div>
                          <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                            <span>{obs.evidence_tier}</span>
                            <span>{formatDate(obs.observed_at)}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </section>

                <section aria-labelledby="regulatory-detail" className="min-w-0">
                  <h2 id="regulatory-detail" className="sr-only">Selected observation detail</h2>
                  {!selectedId || detailQuery.isLoading ? (
                    <LoadingBlock label="observation detail" />
                  ) : !detail ? (
                    <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
                      The selected observation detail could not be loaded.
                    </div>
                  ) : (
                    <div className="space-y-5">
                      <article className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <p className="text-xs uppercase tracking-wide text-slate-500">{detail.observation_id}</p>
                            <h3 className="mt-1 text-xl font-semibold text-slate-100">{detail.provider} · {detail.provider_record_id}</h3>
                          </div>
                          <FreshnessBadge state={detail.freshness_state} />
                        </div>

                        <div className="mt-5">
                          <DetailList items={[
                            { term: 'Record family', value: titleCase(detail.record_family) },
                            { term: 'Evidence tier', value: detail.evidence_tier },
                            { term: 'Observed at', value: formatDate(detail.observed_at) },
                            { term: 'Retrieved at', value: formatDate(detail.retrieved_at) },
                            { term: 'Normalization version', value: detail.normalization_version },
                            { term: 'Source asserted status', value: detail.source_asserted_status },
                          ]} />
                        </div>
                      </article>

                      {detail.identifiers?.length > 0 && (
                        <section aria-labelledby="observation-identifiers" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                          <h3 id="observation-identifiers" className="flex items-center gap-2 font-semibold text-slate-100">
                            <Hash className="h-4 w-4 text-sky-400" aria-hidden="true" /> Identifiers
                          </h3>
                          <ul className="mt-3 space-y-2">
                            {detail.identifiers.map((id) => (
                              <li key={`${id.scheme}-${id.value}`} className="rounded-md border border-slate-800 bg-slate-950/40 p-3 text-sm">
                                <span className="text-slate-500">{id.scheme}:</span>{' '}
                                <span className="text-slate-200">{id.value}</span>
                              </li>
                            ))}
                          </ul>
                        </section>
                      )}

                      <section aria-labelledby="observation-payload" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                        <h3 id="observation-payload" className="font-semibold text-slate-100">Payload</h3>
                        <pre className="mt-3 overflow-auto rounded-md border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-300">
                          {JSON.stringify(detail.payload ?? {}, null, 2)}
                        </pre>
                      </section>

                      <section aria-labelledby="observation-receipt" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                        <h3 id="observation-receipt" className="flex items-center gap-2 font-semibold text-slate-100">
                          <FileText className="h-4 w-4 text-violet-400" aria-hidden="true" /> Source receipt
                        </h3>
                        {detail.receipt ? (
                          <DetailList items={[
                            { term: 'Receipt ID', value: detail.receipt.receipt_id },
                            { term: 'Retrieved at', value: formatDate(detail.receipt.retrieved_at) },
                            { term: 'Retrieval status', value: titleCase(detail.receipt.retrieval_status) },
                            { term: 'HTTP status', value: detail.receipt.http_status },
                            { term: 'SHA-256', value: detail.receipt.sha256 },
                            { term: 'Byte count', value: detail.receipt.byte_count },
                          ]} />
                        ) : (
                          <p className="mt-2 text-sm text-slate-400">No receipt is on record for this observation.</p>
                        )}
                      </section>
                    </div>
                  )}
                </section>
              </div>
            </>
          )}
        </ErrorBoundary>
      </div>
    </div>
  )
}
