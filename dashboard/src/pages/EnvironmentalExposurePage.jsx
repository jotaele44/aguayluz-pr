import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, Database, GitBranch, ShieldCheck } from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import {
  getEnvironmentalExposureIntegrity,
  getEnvironmentalExposureRelationships,
  getEnvironmentalExposureSummary,
  getHazardEvents,
  getHazardIntegrity,
  getHazardSummary,
  getSolidWasteSites,
  SOLID_WASTE_KINDS,
} from '@/lib/environmental-exposure-api'

const pretty = (value) => String(value || 'unknown').replaceAll('_', ' ').toLowerCase()

// Only an LMOP row can state a closure, and only a closed site carries
// valid_until. A missing valid_until therefore means "none recorded", never
// "open": an entity row does not carry the source's own status field.
function closureLabel(site) {
  if (site.valid_until) return `Closed ${site.valid_until}`
  if (site.authority === 'EPA_LMOP') return 'No closure recorded'
  return 'Not stated by source'
}

const siteName = (site) => site.canonical_name || site.name_raw || site.authority_id

const bySite = (a, b) => (
  Number(a.review_status === 'needs_review') - Number(b.review_status === 'needs_review')
  || String(a.municipality || '').localeCompare(String(b.municipality || ''))
  || siteName(a).localeCompare(siteName(b))
)

function SolidWasteSites({ summary }) {
  const sitesQuery = useQuery({
    queryKey: ['environmental-exposure', 'solid-waste-sites'],
    queryFn: getSolidWasteSites,
  })
  const sites = [...(sitesQuery.data?.items ?? [])].sort(bySite)
  // The summary counts every entity by kind. The list client falls back to an
  // empty list on any error, so a list that disagrees with the summary is
  // treated as incomplete instead of being read as "no sites".
  const expected = SOLID_WASTE_KINDS.reduce((sum, kind) => sum + (summary.entity_kind?.[kind] ?? 0), 0)
  const listed = sitesQuery.data?.total ?? 0
  const needsReview = sites.filter((site) => site.review_status === 'needs_review').length
  const mismatch = !sitesQuery.isLoading && (listed !== expected || sites.length !== listed)

  return (
    <section className="mb-6 rounded-lg border border-slate-800 bg-slate-900/60" aria-label="Solid-waste site registry">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <div className="min-w-0 flex-1 basis-96">
          <h2 className="text-sm font-semibold text-slate-100">Solid-waste sites (vertedero registry)</h2>
          <p className="mt-1 text-xs text-slate-500">
            Bounded registry from EPA LMOP and EPA ECHO only. It is not a complete inventory: unauthorized
            dumps, the Puerto Rico solid-waste authority list and EPA Region 2 enforcement records are not
            covered. ECHO rows are classified from facility names and need review. Listing a site says
            nothing about contamination or exposure.
          </p>
        </div>
        <div className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-semibold text-amber-200">
          OPEN
        </div>
      </div>

      {sitesQuery.isLoading ? (
        <div role="status" className="p-5 text-sm text-slate-400">Loading solid-waste sites…</div>
      ) : mismatch ? (
        <div role="alert" className="p-5 text-sm text-red-200">
          The site list ({listed} listed, {sites.length} received) does not match the graph summary
          ({expected}). Treat it as incomplete; no site is implied absent.
        </div>
      ) : sites.length === 0 ? (
        <div className="p-5 text-sm text-slate-400">No solid-waste site records are materialized.</div>
      ) : (
        <>
          <div className="px-4 pt-3 text-xs text-slate-500">
            {sites.length} records · {needsReview} need review
          </div>
          <div className="overflow-x-auto">
            <table className="mt-2 w-full text-left text-xs">
              <thead className="border-y border-slate-800 text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Site</th>
                  <th className="px-4 py-2 font-medium">Kind</th>
                  <th className="px-4 py-2 font-medium">Municipality</th>
                  <th className="px-4 py-2 font-medium">Source record</th>
                  <th className="px-4 py-2 font-medium">Opened</th>
                  <th className="px-4 py-2 font-medium">Closure</th>
                  <th className="px-4 py-2 font-medium">Review</th>
                </tr>
              </thead>
              <tbody>
                {sites.map((site) => (
                  <tr key={site.entity_id} className="border-b border-slate-800/70 last:border-0">
                    <td className="px-4 py-3 text-slate-200">{siteName(site)}</td>
                    <td className="px-4 py-3 text-slate-300">{pretty(site.entity_kind)}</td>
                    <td className="px-4 py-3 text-slate-300">{site.municipality || '—'}</td>
                    <td className="px-4 py-3 font-mono text-[11px] text-slate-400">
                      {site.authority} · {site.authority_id}
                    </td>
                    <td className="px-4 py-3 text-slate-400">{site.valid_from || '—'}</td>
                    <td className="px-4 py-3 text-slate-400">{closureLabel(site)}</td>
                    <td className="px-4 py-3 text-slate-300">{pretty(site.review_status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
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
  const hazardSummaryQuery = useQuery({
    queryKey: ['hazards', 'summary'],
    queryFn: getHazardSummary,
  })
  const hazardEventsQuery = useQuery({
    queryKey: ['hazards', 'events'],
    queryFn: () => getHazardEvents({ limit: 100, current_only: true }),
  })
  const hazardIntegrityQuery = useQuery({
    queryKey: ['hazards', 'integrity'],
    queryFn: getHazardIntegrity,
  })

  const summary = summaryQuery.data
  const relationships = relationshipsQuery.data?.items ?? []
  const integrity = integrityQuery.data
  const pfas = summary?.pfas
  const unavailable = !summary || !integrity

  const hazardSummary = hazardSummaryQuery.data
  const hazardEvents = hazardEventsQuery.data?.items ?? []
  const hazardIntegrity = hazardIntegrityQuery.data

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
                evidence only. They cannot establish contamination, hydraulic connection, exposure,
                disease transmission, or cause.
              </p>
            </div>
          </div>

          <section className="mb-6 rounded-lg border border-slate-800 bg-slate-900/60" aria-label="Puerto Rico hazard advisory plane">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-100">Puerto Rico Hazard & Advisory Plane</h2>
                <p className="mt-1 text-xs text-slate-500">
                  Food recalls, water-health advisories, agriculture/animal health, infectious disease and wastewater surveillance.
                </p>
              </div>
              <div className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-semibold text-amber-200">
                {hazardSummary?.source_universe?.certification_state ?? 'OPEN'}
              </div>
            </div>

            {hazardSummaryQuery.isLoading || hazardIntegrityQuery.isLoading ? (
              <div role="status" className="p-5 text-sm text-slate-400">Loading hazard plane…</div>
            ) : !hazardSummary || !hazardIntegrity ? (
              <div role="alert" className="p-5 text-sm text-red-200">
                Hazard data are unavailable. No health, food, agricultural or causal inference is made.
              </div>
            ) : (
              <>
                <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
                  <MetricCard icon={Database} label="Current records" value={hazardSummary.counts.current_records} detail={`${hazardSummary.counts.records} historical/current rows`} />
                  <MetricCard icon={GitBranch} label="Relationships" value={hazardSummary.counts.relationships} detail={`${hazardSummary.counts.manifestations} frozen manifestations`} />
                  <MetricCard icon={Activity} label="Source families" value={hazardSummary.source_universe.family_count} detail="authoritative denominator remains open" />
                  <MetricCard icon={ShieldCheck} label="Integrity" value={hazardIntegrity.state} detail={`${hazardIntegrity.unresolved?.length ?? 0} structural residue classes`} />
                </div>

                <div className="grid gap-4 border-t border-slate-800 p-4 lg:grid-cols-2">
                  <div>
                    <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Current family counts</div>
                    <div className="mt-2 grid gap-1 text-xs text-slate-300">
                      {Object.keys(hazardSummary.family || {}).length ? Object.entries(hazardSummary.family).map(([family, count]) => (
                        <div key={family} className="flex justify-between gap-4 border-b border-slate-800/60 py-1">
                          <span>{pretty(family)}</span><span className="font-mono">{count}</span>
                        </div>
                      )) : <div className="text-slate-500">No hazard records have been materialized yet.</div>}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Open source-universe residue</div>
                    <ul className="mt-2 grid gap-1 text-xs text-slate-400">
                      {(hazardSummary.source_universe.unresolved_material || []).map((item) => (
                        <li key={item} className="font-mono">{item}</li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className="border-t border-slate-800">
                  <div className="px-4 py-3">
                    <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Current hazard records</h3>
                  </div>
                  {hazardEvents.length === 0 ? (
                    <div className="px-4 pb-4 text-sm text-slate-400">
                      Source contracts are wired, but no production hazard records are materialized yet. This is intentionally fail-closed.
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="border-y border-slate-800 text-slate-500">
                          <tr><th className="px-4 py-2 font-medium">Family</th><th className="px-4 py-2 font-medium">Hazard</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 font-medium">Authority</th><th className="px-4 py-2 font-medium">Municipality</th></tr>
                        </thead>
                        <tbody>
                          {hazardEvents.map((event) => (
                            <tr key={event.record_id} className="border-b border-slate-800/70 last:border-0">
                              <td className="px-4 py-3 text-slate-300">{pretty(event.family)}</td>
                              <td className="px-4 py-3 text-slate-200">{pretty(event.hazard_type)}</td>
                              <td className="px-4 py-3 text-slate-300">{pretty(event.status)}</td>
                              <td className="px-4 py-3 text-slate-400">{event.source_authority}</td>
                              <td className="px-4 py-3 font-mono text-[11px] text-slate-400">{event.municipality_id || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </>
            )}
          </section>

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

              {pfas && (
                <section
                  className="mb-6 rounded-lg border border-slate-800 bg-slate-900/60"
                  aria-label="Puerto Rico PFAS evidence checkpoint"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
                    <div>
                      <h2 className="text-sm font-semibold text-slate-100">
                        Puerto Rico PFAS evidence plane
                      </h2>
                      <p className="mt-1 text-xs text-slate-500">
                        Final EPA UCMR5 occurrence denominator plus regulatory, site, and legal evidence.
                      </p>
                    </div>
                    <div className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-semibold text-amber-200">
                      {pfas.certification_state}
                    </div>
                  </div>

                  <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
                    <MetricCard
                      icon={Database}
                      label="UCMR5 PR rows"
                      value={pfas.occurrence?.total_rows ?? '—'}
                      detail={`${pfas.occurrence?.public_water_system_ids ?? 0} PWS IDs`}
                    />
                    <MetricCard
                      icon={Activity}
                      label="PFAS detections"
                      value={pfas.occurrence?.pfas_reported_detections ?? '—'}
                      detail={`${pfas.occurrence?.pws_ids_with_any_reported_pfas_detection ?? 0} PWS IDs with ≥1 reported detection`}
                    />
                    <MetricCard
                      icon={ShieldCheck}
                      label="Source hashes open"
                      value={pfas.counts?.source_hashes_open ?? '—'}
                      detail={`${pfas.counts?.source_manifestations ?? 0} source manifestations`}
                    />
                    <MetricCard
                      icon={GitBranch}
                      label="Legal manifestations"
                      value={pfas.counts?.legal_manifestations ?? '—'}
                      detail={`${pfas.counts?.primary_legal_dockets_open ?? 0} primary docket freezes open`}
                    />
                  </div>

                  <div className="border-t border-slate-800 px-4 py-3">
                    <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                      Material residue
                    </div>
                    {pfas.unresolved_material?.length ? (
                      <ul className="mt-2 grid gap-1 text-xs text-slate-400">
                        {pfas.unresolved_material.map((item) => (
                          <li key={item} className="font-mono">{item}</li>
                        ))}
                      </ul>
                    ) : (
                      <div className="mt-2 text-xs text-emerald-300">No material residue recorded.</div>
                    )}
                  </div>
                </section>
              )}

              <SolidWasteSites summary={summary} />

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
