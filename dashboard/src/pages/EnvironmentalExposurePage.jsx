import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, Database, GitBranch, ShieldCheck } from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import {
  getEnvironmentalExposureIntegrity,
  getEnvironmentalExposureRelationships,
  getEnvironmentalExposureSummary,
} from '@/lib/environmental-exposure-api'

const pretty = (value) => String(value || 'unknown').replaceAll('_', ' ').toLowerCase()

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

export default function EnvironmentalExposurePage() {
  const summaryQuery = useQuery({
    queryKey: ['environmental-exposure', 'summary'],
    queryFn: getEnvironmentalExposureSummary,
  })
  const relationshipsQuery = useQuery({
    queryKey: ['environmental-exposure', 'relationships'],
    queryFn: () => getEnvironmentalExposureRelationships({ limit: 100 }),
  })
  const integrityQuery = useQuery({
    queryKey: ['environmental-exposure', 'integrity'],
    queryFn: getEnvironmentalExposureIntegrity,
  })

  const summary = summaryQuery.data
  const relationships = relationshipsQuery.data?.items ?? []
  const integrity = integrityQuery.data
  const unavailable = !summary || !integrity

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Environmental Exposure"
        subtitle="Temporal source → pathway → receptor graph with fail-closed causal promotion"
      />
      <div className="flex-1 min-h-0 overflow-auto p-6">
        <ErrorBoundary label="Environmental exposure graph">
          <div
            role="note"
            aria-label="Environmental exposure scope limitation"
            className="mb-5 flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4"
          >
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
            <div>
              <div className="font-semibold text-amber-200">Causation is evidence-gated</div>
              <p className="mt-1 text-sm text-amber-100/80">
                Proximity, nearest-neighbour, name similarity, and source absence are discovery
                evidence only. They cannot establish contamination, hydraulic connection, or cause.
              </p>
            </div>
          </div>

          {summaryQuery.isLoading || integrityQuery.isLoading ? (
            <div role="status" className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 text-sm text-slate-400">
              Loading environmental exposure graph…
            </div>
          ) : unavailable ? (
            <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
              The environmental exposure API is unavailable. No exposure relationship is inferred.
            </div>
          ) : (
            <>
              <section className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Environmental exposure graph summary">
                <MetricCard
                  icon={Database}
                  label="Entities"
                  value={summary.counts.entities}
                  detail={`${summary.counts.observations} observations`}
                />
                <MetricCard
                  icon={GitBranch}
                  label="Relationships"
                  value={summary.counts.relationships}
                  detail={`${Object.keys(summary.predicate || {}).length} predicates observed`}
                />
                <MetricCard
                  icon={Activity}
                  label="Geometries"
                  value={summary.counts.geometries}
                  detail={`${summary.counts.events} exposure events`}
                />
                <MetricCard
                  icon={ShieldCheck}
                  label="Structural integrity"
                  value={integrity.structural_integrity_state}
                  detail={`${integrity.error_count} validation errors · corpus ${String(integrity.corpus_certification_state || 'OPEN').toLowerCase()}`}
                />
              </section>

              <section className="rounded-lg border border-slate-800 bg-slate-900/60">
                <div className="border-b border-slate-800 px-4 py-3">
                  <h2 className="text-sm font-semibold text-slate-100">Temporal relationships</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    Empty is a valid state: structural integrity is not a claim that the public-source corpus is complete.
                  </p>
                </div>
                {relationships.length === 0 ? (
                  <div className="p-5 text-sm text-slate-400">
                    No adjudicated or candidate exposure relationships are currently materialized.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="border-b border-slate-800 text-slate-500">
                        <tr>
                          <th className="px-4 py-2 font-medium">Predicate</th>
                          <th className="px-4 py-2 font-medium">Causal state</th>
                          <th className="px-4 py-2 font-medium">Subject</th>
                          <th className="px-4 py-2 font-medium">Object</th>
                          <th className="px-4 py-2 font-medium">Evidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {relationships.map((edge) => (
                          <tr key={edge.relationship_id} className="border-b border-slate-800/70 last:border-0">
                            <td className="px-4 py-3 text-slate-200">{pretty(edge.predicate)}</td>
                            <td className="px-4 py-3 text-slate-300">{pretty(edge.causal_state)}</td>
                            <td className="px-4 py-3 font-mono text-[11px] text-slate-400">{edge.subject_id}</td>
                            <td className="px-4 py-3 font-mono text-[11px] text-slate-400">{edge.object_id}</td>
                            <td className="px-4 py-3 text-slate-400">
                              {(edge.evidence_classes || []).map(pretty).join(', ') || 'none'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </ErrorBoundary>
      </div>
    </div>
  )
}
