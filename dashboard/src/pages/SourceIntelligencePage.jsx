import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, CheckCircle2, Database, FileCheck2, Network, ShieldCheck,
} from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import Panel from '@/components/common/Panel'
import {
  getSourceIntelligenceCoverage,
  getSourceIntelligenceDomains,
  getSourceIntelligenceProducts,
  getSourceIntelligenceRouteGovernance,
  getSourceIntelligenceRoutes,
  getSourceIntelligenceSources,
  getSourceIntelligenceSummary,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const titleCase = (value) => String(value || 'unknown')
  .replaceAll('_', ' ')
  .toLowerCase()
  .replace(/\b\w/g, (letter) => letter.toUpperCase())

function Badge({ state }) {
  const value = String(state || 'UNKNOWN')
  const pass = ['PASS', 'VERIFIED', 'REGISTERED', 'CANONICAL_ROUTE', 'EMBEDDED', 'FROZEN_V1_CERTIFIED'].includes(value)
  const open = value.includes('OPEN') || value.includes('PROVISIONAL') || value.includes('UNKNOWN')
  return (
    <span className={cn(
      'inline-flex rounded-full border px-2 py-0.5 font-mono text-[10px] font-semibold',
      pass && 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
      open && 'border-amber-500/40 bg-amber-500/10 text-amber-300',
      !pass && !open && 'border-slate-700 bg-slate-900 text-slate-300',
    )}>
      {value}
    </span>
  )
}

function Metric({ label, value, detail, icon: Icon }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-500">
        <Icon className="h-4 w-4" aria-hidden="true" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
      <div className="mt-1 text-xs text-slate-500">{detail}</div>
    </div>
  )
}

function SelectField({ label, value, onChange, children }) {
  return (
    <label className="flex min-w-[180px] flex-col gap-1 text-[10px] uppercase tracking-wide text-slate-500">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-xs normal-case text-slate-200"
      >
        {children}
      </select>
    </label>
  )
}

function Empty({ children }) {
  return <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-5 text-sm text-slate-400">{children}</div>
}

export default function SourceIntelligencePage() {
  const [domainId, setDomainId] = useState('ENERGY_GENERATION')
  const [sourceId, setSourceId] = useState('EIA_860M')

  const query = useQuery({
    queryKey: ['source-intelligence', 'v1'],
    queryFn: async () => {
      const [summary, domains, sources, coverage, products, routes, routeGovernance] = await Promise.all([
        getSourceIntelligenceSummary(),
        getSourceIntelligenceDomains(),
        getSourceIntelligenceSources(),
        getSourceIntelligenceCoverage(),
        getSourceIntelligenceProducts(),
        getSourceIntelligenceRoutes(),
        getSourceIntelligenceRouteGovernance(),
      ])
      return { summary, domains, sources, coverage, products, routes, routeGovernance }
    },
  })

  const data = query.data
  const domains = data?.domains?.items ?? []
  const sources = data?.sources?.items ?? []
  const requirements = data?.coverage?.items ?? []
  const products = data?.products?.items ?? []
  const routes = data?.routes?.items ?? []
  const governance = data?.routeGovernance?.summary ?? data?.summary?.route_governance ?? {}
  const summary = data?.summary

  const selectedDomain = domains.find((row) => row.domain_id === domainId) ?? domains[0]
  const selectedSource = sources.find((row) => row.source_family_id === sourceId) ?? sources[0]

  const domainRequirements = useMemo(
    () => requirements.filter((row) => row.domain_id === selectedDomain?.domain_id),
    [requirements, selectedDomain],
  )
  const sourceProducts = useMemo(
    () => products.filter((row) => row.source_family_id === selectedSource?.source_family_id),
    [products, selectedSource],
  )
  const sourceRoutes = useMemo(() => {
    const ids = new Set(sourceProducts.map((row) => row.product_id))
    return routes.filter((row) => ids.has(row.product_id))
  }, [routes, sourceProducts])

  const openFamilies = governance.open_payload_product_denominator_family_ids ?? []
  const exhaustedFamilies = governance.payload_product_denominator_exhausted_family_ids ?? []
  const readiness = summary?.backend_readiness
  const sourceUniverseCertified = Boolean(summary?.source_universe_certified)

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Source Intelligence"
        subtitle="Governed source coverage, runtime health, route provenance, and fail-closed certification boundaries"
      />
      <div className="flex-1 min-h-0 overflow-auto p-6">
        <ErrorBoundary label="Source Intelligence">
          {query.isLoading ? (
            <Empty>Loading governed source-intelligence state…</Empty>
          ) : query.isError || !data ? (
            <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-sm text-red-200">
              The Source Intelligence API is unavailable. No coverage, health, or certification state is inferred.
            </div>
          ) : (
            <div className="space-y-6">
              <div
                role="note"
                className={cn(
                  'flex items-start gap-3 rounded-lg border p-4',
                  sourceUniverseCertified
                    ? 'border-emerald-500/30 bg-emerald-500/10'
                    : 'border-amber-500/30 bg-amber-500/10',
                )}
              >
                {sourceUniverseCertified
                  ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300" aria-hidden="true" />
                  : <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />}
                <div>
                  <div className={cn('font-semibold', sourceUniverseCertified ? 'text-emerald-200' : 'text-amber-200')}>
                    {sourceUniverseCertified ? 'Source universe certified' : 'Backend certified; source universe still open'}
                  </div>
                  <p className="mt-1 text-sm text-slate-300">
                    {summary.scope} Domain certification and payload-denominator exhaustion remain separate gates.
                  </p>
                </div>
              </div>

              <section aria-label="Source Intelligence metrics" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Metric
                  icon={ShieldCheck}
                  label="Backend readiness"
                  value={readiness?.score ?? 0}
                  detail={summary.api_contract_state}
                />
                <Metric
                  icon={Database}
                  label="Source families"
                  value={summary.coverage?.total_source_families ?? sources.length}
                  detail={`${governance.governed_source_families ?? 0} governed`}
                />
                <Metric
                  icon={FileCheck2}
                  label="Verified products"
                  value={governance.verified_product_identity_count ?? 0}
                  detail={`${governance.total_products ?? products.length} registered products`}
                />
                <Metric
                  icon={Network}
                  label="Payload denominator"
                  value={exhaustedFamilies.length}
                  detail={`${openFamilies.length} source families still open`}
                />
              </section>

              <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
                <div className="space-y-6">
                  <Panel title="Coverage matrix">
                    <div className="mb-4 flex flex-wrap gap-3">
                      <SelectField label="Domain" value={selectedDomain?.domain_id ?? ''} onChange={setDomainId}>
                        {domains.map((row) => <option key={row.domain_id} value={row.domain_id}>{row.label}</option>)}
                      </SelectField>
                    </div>
                    {selectedDomain && (
                      <div className="mb-4 rounded-md border border-slate-800 bg-slate-950/40 p-3">
                        <div className="text-sm font-medium text-slate-200">{selectedDomain.label}</div>
                        <div className="mt-1 text-xs text-slate-500">{selectedDomain.scope}</div>
                        <div className="mt-2 text-[10px] uppercase tracking-wide text-slate-600">
                          Certification: {selectedDomain.certification_rule}
                        </div>
                      </div>
                    )}
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="border-b border-slate-800 text-[10px] uppercase tracking-wide text-slate-500">
                          <tr>
                            <th className="px-2 py-2">Source family</th>
                            <th className="px-2 py-2">Role</th>
                            <th className="px-2 py-2">Required</th>
                            <th className="px-2 py-2">Adapter</th>
                            <th className="px-2 py-2">State</th>
                          </tr>
                        </thead>
                        <tbody>
                          {domainRequirements.map((row) => (
                            <tr key={`${row.domain_id}:${row.source_family_id}`} className="border-b border-slate-900">
                              <td className="px-2 py-2 font-mono text-sky-300">{row.source_family_id}</td>
                              <td className="px-2 py-2 text-slate-300">{titleCase(row.role)}</td>
                              <td className="px-2 py-2 text-slate-400">{row.required ? 'yes' : 'no'}</td>
                              <td className="px-2 py-2 text-slate-400">{row.adapter_required ? 'required' : 'not required'}</td>
                              <td className="px-2 py-2"><Badge state={row.state} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Panel>

                  <Panel title="Source health and provenance">
                    <div className="mb-4 flex flex-wrap gap-3">
                      <SelectField label="Source family" value={selectedSource?.source_family_id ?? ''} onChange={setSourceId}>
                        {sources.map((row) => <option key={row.source_family_id} value={row.source_family_id}>{row.label}</option>)}
                      </SelectField>
                    </div>
                    {selectedSource ? (
                      <div className="space-y-4">
                        <div className="grid gap-3 sm:grid-cols-2">
                          {[
                            ['Authority', selectedSource.authority],
                            ['Identity namespace', selectedSource.identity_namespace],
                            ['Monitoring mode', titleCase(selectedSource.monitoring_mode)],
                            ['Adapter', selectedSource.adapter_id || 'None registered'],
                            ['Mutable', selectedSource.mutable ? 'yes' : 'no'],
                            ['Runtime health', selectedSource.runtime_health?.state ?? selectedSource.runtime_health_reason],
                          ].map(([label, value]) => (
                            <div key={label} className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
                              <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
                              <div className="mt-1 break-words text-sm text-slate-200">{value || 'Unknown'}</div>
                            </div>
                          ))}
                        </div>
                        <div>
                          <div className="text-[10px] uppercase tracking-wide text-slate-500">Canonical locator</div>
                          <div className="mt-1 break-all font-mono text-xs text-slate-300">{selectedSource.canonical_locator}</div>
                        </div>
                        <div>
                          <div className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">Requirements</div>
                          <div className="flex flex-wrap gap-2">
                            {(selectedSource.requirements ?? []).map((row) => (
                              <span key={`${row.domain_id}:${row.role}`} className="rounded-md border border-slate-800 bg-slate-950 px-2 py-1 text-[10px] text-slate-300">
                                {row.domain_id} · {titleCase(row.role)}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : <Empty>No source family is registered.</Empty>}
                  </Panel>
                </div>

                <div className="space-y-6">
                  <Panel title="Certification gaps">
                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs text-slate-400">API contract</span>
                        <Badge state={summary.api_contract_state} />
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs text-slate-400">Coverage matrix</span>
                        <Badge state={summary.coverage_matrix_ready ? 'PASS' : 'OPEN'} />
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs text-slate-400">Route governance</span>
                        <Badge state={governance.route_governance_coverage_complete ? 'PASS' : 'OPEN'} />
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs text-slate-400">Payload denominator</span>
                        <Badge state={governance.payload_product_denominator_complete ? 'PASS' : 'OPEN'} />
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs text-slate-400">Domain certification</span>
                        <Badge state={summary.domain_certification_complete ? 'PASS' : 'OPEN'} />
                      </div>
                    </div>
                    {openFamilies.length > 0 && (
                      <div className="mt-4 border-t border-slate-800 pt-4">
                        <div className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">
                          Open payload-product denominator families ({openFamilies.length})
                        </div>
                        <div className="max-h-64 space-y-1 overflow-auto">
                          {openFamilies.map((id) => (
                            <button
                              key={id}
                              type="button"
                              onClick={() => setSourceId(id)}
                              className="block w-full rounded px-2 py-1 text-left font-mono text-[11px] text-amber-300 hover:bg-slate-800"
                            >
                              {id}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </Panel>

                  <Panel title="Evidence / provenance">
                    {selectedSource ? (
                      <div className="space-y-4">
                        <div>
                          <div className="text-[10px] uppercase tracking-wide text-slate-500">Source family</div>
                          <div className="mt-1 font-mono text-sm text-sky-300">{selectedSource.source_family_id}</div>
                        </div>
                        <div>
                          <div className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">
                            Products ({sourceProducts.length})
                          </div>
                          <div className="space-y-2">
                            {sourceProducts.map((row) => (
                              <div key={row.product_id} className="rounded-md border border-slate-800 bg-slate-950/40 p-2">
                                <div className="font-mono text-[11px] text-slate-200">{row.product_id}</div>
                                <div className="mt-1 flex flex-wrap gap-2">
                                  <Badge state={row.identity_state} />
                                  <Badge state={row.payload_state} />
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div>
                          <div className="mb-2 text-[10px] uppercase tracking-wide text-slate-500">
                            Acquisition routes ({sourceRoutes.length})
                          </div>
                          <div className="max-h-80 space-y-2 overflow-auto">
                            {sourceRoutes.map((row) => (
                              <div key={row.route_id} className="rounded-md border border-slate-800 bg-slate-950/40 p-2">
                                <div className="font-mono text-[11px] text-violet-300">{row.route_id}</div>
                                <div className="mt-1 text-[10px] text-slate-500">
                                  {row.role} · {row.representation} · priority {row.priority}
                                </div>
                                <div className="mt-1 break-all font-mono text-[10px] text-slate-600">{row.locator}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : <Empty>No source selected.</Empty>}
                  </Panel>
                </div>
              </div>
            </div>
          )}
        </ErrorBoundary>
      </div>
    </div>
  )
}
