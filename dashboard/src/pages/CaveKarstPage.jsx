import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Clock3,
  Database,
  Droplets,
  ExternalLink,
  MapPinOff,
  Mountain,
  Network,
  ShieldCheck,
  Wrench,
} from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import {
  getCaveKarstAlerts,
  getCaveKarstAsset,
  getCaveKarstAssets,
  getCaveKarstEdges,
  getCaveKarstProvenance,
  getCaveKarstStatusHistory,
  getCaveKarstSummary,
} from '@/lib/cave-karst-api'
import { cn } from '@/lib/utils'

const titleCase = (value) => String(value || 'unknown')
  .replaceAll('_', ' ')
  .replace(/\b\w/g, (letter) => letter.toUpperCase())

const formatDate = (value) => {
  if (!value) return 'Unknown'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function StatusBadge({ status }) {
  const normalized = status || 'unknown'
  return (
    <span className={cn(
      'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold',
      normalized === 'open' && 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
      normalized === 'closed' && 'border-red-500/40 bg-red-500/10 text-red-300',
      ['restricted', 'partially_open', 'maintenance'].includes(normalized)
        && 'border-amber-500/40 bg-amber-500/10 text-amber-300',
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
          <dd className="mt-1 text-sm text-slate-200">{value || 'Unknown'}</dd>
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

export default function CaveKarstPage() {
  const [selectedId, setSelectedId] = useState(null)
  const summaryQuery = useQuery({
    queryKey: ['cave-karst', 'summary'],
    queryFn: getCaveKarstSummary,
  })
  const assetsQuery = useQuery({
    queryKey: ['cave-karst', 'assets'],
    queryFn: () => getCaveKarstAssets(),
  })
  const alertsQuery = useQuery({
    queryKey: ['cave-karst', 'alerts'],
    queryFn: () => getCaveKarstAlerts(),
  })

  const assets = assetsQuery.data?.items ?? []
  useEffect(() => {
    if (!selectedId && assets.length) setSelectedId(assets[0].asset_id)
  }, [assets, selectedId])

  const detailQuery = useQuery({
    queryKey: ['cave-karst', 'asset', selectedId],
    queryFn: () => getCaveKarstAsset(selectedId),
    enabled: Boolean(selectedId),
  })
  const historyQuery = useQuery({
    queryKey: ['cave-karst', 'history', selectedId],
    queryFn: () => getCaveKarstStatusHistory(selectedId),
    enabled: Boolean(selectedId),
  })
  const provenanceQuery = useQuery({
    queryKey: ['cave-karst', 'provenance', selectedId],
    queryFn: () => getCaveKarstProvenance(selectedId),
    enabled: Boolean(selectedId),
  })
  const edgesQuery = useQuery({
    queryKey: ['cave-karst', 'edges', selectedId],
    queryFn: () => getCaveKarstEdges(selectedId),
    enabled: Boolean(selectedId),
  })

  const summary = summaryQuery.data
  const detail = detailQuery.data
  const activeAlerts = alertsQuery.data?.items ?? []
  const selectedAlerts = useMemo(
    () => activeAlerts.filter((item) => item.asset_id === selectedId),
    [activeAlerts, selectedId],
  )

  const queryFailed = summaryQuery.isError || assetsQuery.isError || !summary

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Cave & Karst Monitor"
        subtitle="Read-only Río Camuy pilot registry — not a statewide cave census"
      />
      <div className="flex-1 min-h-0 overflow-auto p-6">
        <ErrorBoundary label="Cave and karst monitor">
          <div
            role="note"
            aria-label="Registry scope limitation"
            className="mb-5 flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4"
          >
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
            <div>
              <div className="font-semibold text-amber-200">Pilot scope only</div>
              <p className="mt-1 text-sm text-amber-100/80">
                {summary?.scope?.statement
                  ?? 'Río Camuy pilot registry only. Statewide completeness is not asserted.'}
              </p>
            </div>
          </div>

          {summaryQuery.isLoading || assetsQuery.isLoading ? (
            <LoadingBlock label="registry" />
          ) : queryFailed ? (
            <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
              The cave and karst read API is unavailable. No operational state is inferred.
            </div>
          ) : (
            <>
              <section aria-labelledby="cave-karst-overview" className="mb-6">
                <h2 id="cave-karst-overview" className="sr-only">Registry overview</h2>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                  <MetricCard icon={Mountain} label="Pilot assets" value={summary.counts.assets} detail="Río Camuy scope" />
                  <MetricCard icon={Database} label="Sources" value={summary.counts.sources} detail={`${summary.counts.status_events} status events`} />
                  <MetricCard icon={Network} label="Graph edges" value={summary.counts.edges} detail={`${summary.counts.observations} observations`} />
                  <MetricCard icon={AlertTriangle} label="Active alerts" value={summary.counts.alerts} detail={`${summary.counts.unresolved_gaps} unresolved gaps`} />
                  <MetricCard
                    icon={ShieldCheck}
                    label="Registry validation"
                    value={summary.validation.ok ? 'Pass' : 'Review'}
                    detail={`${summary.validation.contradiction_count} contradictions`}
                  />
                </div>
              </section>

              <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
                <section aria-labelledby="cave-karst-assets">
                  <div className="mb-3 flex items-center justify-between">
                    <h2 id="cave-karst-assets" className="text-sm font-semibold text-slate-100">Pilot assets</h2>
                    <span className="text-xs text-slate-500">{assets.length} records</span>
                  </div>
                  <div className="space-y-2">
                    {assets.map((asset) => (
                      <button
                        key={asset.asset_id}
                        type="button"
                        aria-pressed={selectedId === asset.asset_id}
                        onClick={() => setSelectedId(asset.asset_id)}
                        className={cn(
                          'w-full rounded-lg border p-3 text-left transition-colors',
                          selectedId === asset.asset_id
                            ? 'border-sky-500/50 bg-sky-500/10'
                            : 'border-slate-800 bg-slate-900/60 hover:border-slate-700 hover:bg-slate-900',
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-slate-100">{asset.canonical_name}</div>
                            <div className="mt-1 text-xs text-slate-500">{titleCase(asset.asset_kind)}</div>
                          </div>
                          <StatusBadge status={asset.current_status} />
                        </div>
                        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                          <span>{asset.evidence_tier} · {asset.confidence}% confidence</span>
                          <span>{asset.unresolved_gaps.length} gaps</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>

                <section aria-labelledby="cave-karst-detail" className="min-w-0">
                  <h2 id="cave-karst-detail" className="sr-only">Selected asset detail</h2>
                  {!selectedId || detailQuery.isLoading ? (
                    <LoadingBlock label="asset detail" />
                  ) : !detail ? (
                    <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
                      The selected asset detail could not be loaded.
                    </div>
                  ) : (
                    <div className="space-y-5">
                      <article className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <p className="text-xs uppercase tracking-wide text-slate-500">{detail.asset_id}</p>
                            <h3 className="mt-1 text-xl font-semibold text-slate-100">{detail.canonical_name}</h3>
                            <p className="mt-1 text-sm text-slate-400">{detail.municipalities?.join(', ') || 'Municipality unknown'}</p>
                          </div>
                          <StatusBadge status={detail.current_status} />
                        </div>

                        <div className="mt-5">
                          <DetailList items={[
                            { term: 'Status as of', value: formatDate(detail.status_as_of) },
                            { term: 'Freshness', value: detail.freshness?.stale ? `Stale (${detail.freshness.age_days ?? 'unknown'} days)` : `Current (${detail.freshness?.age_days ?? 0} days)` },
                            { term: 'Confidence', value: `${detail.confidence}%` },
                            { term: 'Evidence tier', value: detail.evidence_tier },
                            { term: 'Review status', value: titleCase(detail.review_status) },
                            { term: 'Operator', value: detail.operational?.operator },
                          ]} />
                        </div>
                      </article>

                      <div className="grid gap-5 lg:grid-cols-2">
                        <section aria-labelledby="hydrologic-profile" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                          <h3 id="hydrologic-profile" className="flex items-center gap-2 font-semibold text-slate-100">
                            <Droplets className="h-4 w-4 text-sky-400" aria-hidden="true" /> Hydrologic profile
                          </h3>
                          <DetailList items={[
                            { term: 'Roles', value: detail.hydrologic?.roles?.map(titleCase).join(', ') },
                            { term: 'Flood sensitivity', value: titleCase(detail.hydrologic?.flood_sensitivity) },
                            { term: 'Monitoring', value: titleCase(detail.hydrologic?.monitoring_status) },
                            { term: 'Surface-water connection', value: titleCase(detail.hydrologic?.surface_water_connection) },
                          ]} />
                        </section>

                        <section aria-labelledby="infrastructure-profile" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                          <h3 id="infrastructure-profile" className="flex items-center gap-2 font-semibold text-slate-100">
                            <Wrench className="h-4 w-4 text-amber-400" aria-hidden="true" /> Infrastructure
                          </h3>
                          <DetailList items={[
                            { term: 'Condition', value: titleCase(detail.infrastructure?.condition) },
                            { term: 'Emergency access', value: titleCase(detail.infrastructure?.emergency_access) },
                            { term: 'Power dependency', value: titleCase(detail.infrastructure?.power_dependency) },
                            { term: 'Components', value: detail.infrastructure?.components?.map(titleCase).join(', ') },
                          ]} />
                        </section>
                      </div>

                      <section aria-labelledby="coordinate-policy" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                        <h3 id="coordinate-policy" className="flex items-center gap-2 font-semibold text-slate-100">
                          <MapPinOff className="h-4 w-4 text-slate-400" aria-hidden="true" /> Coordinate disclosure
                        </h3>
                        <p className="mt-2 text-sm text-slate-300">
                          {detail.coordinates_redacted
                            ? 'Precise coordinates are withheld by the registry disclosure policy.'
                            : 'This asset is explicitly classified for public exact-coordinate display.'}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">Policy: {titleCase(detail.location_disclosure)}</p>
                      </section>

                      <section aria-labelledby="unresolved-gaps" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                        <h3 id="unresolved-gaps" className="font-semibold text-slate-100">Unresolved gaps</h3>
                        {detail.unresolved_gaps?.length ? (
                          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                            {detail.unresolved_gaps.map((gap) => (
                              <li key={gap} className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-100">
                                {titleCase(gap)}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="mt-2 text-sm text-slate-400">No unresolved gaps are recorded for this asset.</p>
                        )}
                      </section>

                      <section aria-labelledby="asset-alerts" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                        <h3 id="asset-alerts" className="font-semibold text-slate-100">Active alerts</h3>
                        {selectedAlerts.length ? (
                          <ul className="mt-3 space-y-2">
                            {selectedAlerts.map((alert) => (
                              <li key={alert.alert_id} className="rounded-md border border-red-500/20 bg-red-500/5 p-3">
                                <div className="flex items-center justify-between gap-3">
                                  <span className="text-sm font-medium text-red-100">{titleCase(alert.alert_type)}</span>
                                  <span className="text-xs text-red-300">Severity {alert.severity}</span>
                                </div>
                                <p className="mt-1 text-sm text-slate-300">{alert.summary}</p>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="mt-2 text-sm text-slate-400">No active derived alerts.</p>
                        )}
                      </section>

                      <div className="grid gap-5 xl:grid-cols-2">
                        <section aria-labelledby="status-history" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                          <h3 id="status-history" className="flex items-center gap-2 font-semibold text-slate-100">
                            <Clock3 className="h-4 w-4 text-sky-400" aria-hidden="true" /> Status history
                          </h3>
                          {historyQuery.isLoading ? <LoadingBlock label="status history" /> : (
                            <ol className="mt-3 space-y-3">
                              {(historyQuery.data?.items ?? []).map((event) => (
                                <li key={event.event_id} className="border-l border-slate-700 pl-3">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <StatusBadge status={event.to_status} />
                                    <span className="text-xs text-slate-500">{formatDate(event.effective_from || event.observed_at)}</span>
                                  </div>
                                  <p className="mt-1 text-xs text-slate-400">{titleCase(event.event_type)} · {event.evidence_tier} · {titleCase(event.review_status)}</p>
                                </li>
                              ))}
                            </ol>
                          )}
                        </section>

                        <section aria-labelledby="graph-edges" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                          <h3 id="graph-edges" className="flex items-center gap-2 font-semibold text-slate-100">
                            <Network className="h-4 w-4 text-violet-400" aria-hidden="true" /> Graph edges
                          </h3>
                          {edgesQuery.isLoading ? <LoadingBlock label="graph edges" /> : (
                            <ul className="mt-3 space-y-2">
                              {(edgesQuery.data?.items ?? []).map((edge) => (
                                <li key={edge.edge_id} className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
                                  <div className="text-sm text-slate-200">{titleCase(edge.relation)}</div>
                                  <div className="mt-1 text-xs text-slate-500">{titleCase(edge.direction)} · {edge.to_node_id} · {edge.confidence}%</div>
                                </li>
                              ))}
                            </ul>
                          )}
                        </section>
                      </div>

                      <section aria-labelledby="provenance" className="rounded-lg border border-slate-800 bg-slate-900/70 p-5">
                        <h3 id="provenance" className="font-semibold text-slate-100">Provenance</h3>
                        <p className="mt-1 text-xs text-slate-500">{provenanceQuery.data?.evidence_policy}</p>
                        {provenanceQuery.isLoading ? <LoadingBlock label="provenance" /> : (
                          <ul className="mt-3 space-y-3">
                            {(provenanceQuery.data?.items ?? []).map((source) => (
                              <li key={source.source_id} className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                  <div>
                                    <div className="text-sm font-medium text-slate-100">{source.title}</div>
                                    <div className="mt-1 text-xs text-slate-500">{source.publisher} · {source.evidence_tier} · {titleCase(source.review_status)}</div>
                                  </div>
                                  {source.url && (
                                    <a
                                      href={source.url}
                                      target="_blank"
                                      rel="noreferrer noopener"
                                      className="inline-flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300"
                                      aria-label={`Open source: ${source.title}`}
                                    >
                                      Source <ExternalLink className="h-3 w-3" aria-hidden="true" />
                                    </a>
                                  )}
                                </div>
                                {source.notes && <p className="mt-2 text-xs text-slate-400">{source.notes}</p>}
                              </li>
                            ))}
                          </ul>
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
