import { useMemo, useState } from 'react'
import { AlertTriangle, Database, Eye, EyeOff, GitBranch, MapPinned, ShieldCheck } from 'lucide-react'
import { useAssets, useMunicipiosGeojson } from '@/lib/hooks'
import AssetMap from '@/components/AssetMap'
import AssetsTable from '@/components/AssetsTable'
import AssetDetail from '@/components/AssetDetail'
import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'

const STATUS_META = {
  confirmed: { label: 'Confirmed', className: 'border-red-500/40 bg-red-500/10 text-red-300' },
  suspected: { label: 'Suspected', className: 'border-amber-500/40 bg-amber-500/10 text-amber-300' },
  derived: { label: 'Derived', className: 'border-sky-500/40 bg-sky-500/10 text-sky-300' },
  stale: { label: 'Stale', className: 'border-violet-500/40 bg-violet-500/10 text-violet-300' },
  unknown: { label: 'Unknown', className: 'border-slate-700 bg-slate-900 text-slate-400' },
}

function Stat({ label, value, detail }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 font-mono text-xl font-semibold text-slate-100">{value ?? 0}</div>
      {detail && <div className="mt-1 text-[11px] text-slate-500">{detail}</div>}
    </div>
  )
}

function StatusBadge({ status }) {
  const meta = STATUS_META[status] ?? STATUS_META.unknown
  return <span className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase ${meta.className}`}>{meta.label}</span>
}

function CountList({ values, limit = 8 }) {
  const entries = Object.entries(values ?? {}).slice(0, limit)
  if (!entries.length) return <div className="text-xs text-slate-500">No records.</div>
  return (
    <div className="space-y-1.5">
      {entries.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between gap-3 text-xs">
          <span className="truncate text-slate-400">{label}</span>
          <span className="font-mono text-slate-200">{value}</span>
        </div>
      ))}
    </div>
  )
}

export default function AssetsPage() {
  const [view, setView] = useState('public')
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(null)
  const [panel, setPanel] = useState('switchboard')
  const { data: municipios } = useMunicipiosGeojson()
  const { data, isLoading } = useAssets({
    impact: true,
    view,
    impact_status: status || undefined,
    search: search || undefined,
  })

  const payload = Array.isArray(data) ? null : data
  const assets = payload?.assets ?? (Array.isArray(data) ? data : [])
  const impactCounts = payload?.impact_counts ?? {}
  const inventory = payload?.inventory ?? {}
  const operatorAvailable = Boolean(payload?.operator_view_available)

  const assetGeo = useMemo(() => ({
    type: 'FeatureCollection',
    features: assets
      .filter((asset) => Number.isFinite(asset.lat) && Number.isFinite(asset.lon))
      .map((asset) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [asset.lon, asset.lat] },
        properties: asset,
      })),
  }), [assets])

  const exposedRelationships = (payload?.relationships ?? [])
    .filter((item) => item.propagation_allowed)
    .slice(0, 100)
  const timeline = (payload?.timeline ?? []).slice(0, 100)
  const contradictions = (payload?.contradictions ?? []).slice(0, 50)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title="Asset Impact Switchboard"
        subtitle="Versioned water-infrastructure baseline with evidence-bound direct and derived impact states"
      />

      <div className="border-b border-slate-800 bg-slate-950 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setPanel('switchboard')}
            className={`rounded px-3 py-1.5 text-xs font-medium ${panel === 'switchboard' ? 'bg-sky-500/20 text-sky-300' : 'bg-slate-900 text-slate-400'}`}
          >
            Switchboard
          </button>
          <button
            type="button"
            onClick={() => setPanel('inventory')}
            className={`rounded px-3 py-1.5 text-xs font-medium ${panel === 'inventory' ? 'bg-sky-500/20 text-sky-300' : 'bg-slate-900 text-slate-400'}`}
          >
            Inventory
          </button>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 rounded border border-slate-800 bg-slate-900 px-2 py-1 text-xs text-slate-400">
              {view === 'public' ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
              <select
                aria-label="Asset detail view"
                value={view}
                onChange={(event) => setView(event.target.value)}
                className="bg-transparent text-slate-200 outline-none"
              >
                <option value="public">Public view</option>
                <option value="operator" disabled={!operatorAvailable}>Operator view</option>
              </select>
            </label>
            <select
              aria-label="Impact status filter"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="rounded border border-slate-800 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
            >
              <option value="">All impact states</option>
              {Object.keys(STATUS_META).map((key) => <option key={key} value={key}>{STATUS_META[key].label}</option>)}
            </select>
            <input
              aria-label="Search switchboard assets"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search asset, ID, municipio"
              className="w-56 rounded border border-slate-800 bg-slate-900 px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600"
            />
          </div>
        </div>
        {!operatorAvailable && (
          <div className="mt-2 text-[11px] text-slate-500">
            Operator detail is runtime-gated. Public view withholds exact control-asset coordinates and source references.
          </div>
        )}
      </div>

      {panel === 'inventory' ? (
        <div className="flex-1 min-h-0">
          <ErrorBoundary label="Asset inventory">
            <AssetsTable assets={assets} isLoading={isLoading} selectedId={selected?.asset_id} onSelect={setSelected} syncUrl />
          </ErrorBoundary>
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
          <section aria-label="Asset impact summary" className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
            <Stat label="Canonical assets" value={inventory.canonical_asset_total} detail={`${inventory.records_collapsed ?? 0} records collapsed`} />
            <Stat label="Relationships" value={payload?.relationship_count} detail={`${payload?.derived_path_count ?? 0} propagated paths`} />
            {Object.keys(STATUS_META).map((key) => (
              <Stat key={key} label={STATUS_META[key].label} value={impactCounts[key]} />
            ))}
            <Stat label="Contradictions" value={payload?.contradiction_count} />
          </section>

          <section className="rounded-lg border border-slate-800 bg-slate-950 overflow-hidden">
            <div className="flex items-center gap-2 border-b border-slate-800 px-3 py-2">
              <MapPinned className="h-4 w-4 text-sky-400" />
              <div>
                <div className="text-xs font-semibold text-slate-200">Impact map</div>
                <div className="text-[11px] text-slate-500">Select a marker for its evidence, dependency exposure, and restoration context.</div>
              </div>
            </div>
            <div className="h-[420px]">
              <ErrorBoundary label="Asset impact map">
                <AssetMap
                  assets={assetGeo}
                  assetRows={assets}
                  municipios={municipios}
                  events={[]}
                  alerts={{ type: 'FeatureCollection', features: [] }}
                  selectedAssetId={selected?.asset_id}
                  onSelect={(props) => setSelected(assets.find((asset) => asset.asset_id === props.asset_id) ?? props)}
                />
              </ErrorBoundary>
            </div>
          </section>

          <div className="grid gap-4 xl:grid-cols-3">
            <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-200">
                <Database className="h-4 w-4 text-sky-400" /> Baseline coverage
              </div>
              <div className="grid grid-cols-2 gap-3">
                <CountList values={inventory.by_type} />
                <CountList values={inventory.provenance_class} />
              </div>
              <div className="mt-3 border-t border-slate-800 pt-3 text-xs text-slate-400">
                Municipios represented: <span className="font-mono text-slate-200">{payload?.municipio_accounting?.represented_count ?? 0}/{payload?.municipio_accounting?.expected_count ?? 0}</span>
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-200">
                <GitBranch className="h-4 w-4 text-sky-400" /> Dependency graph
              </div>
              <div className="max-h-64 space-y-2 overflow-y-auto">
                {exposedRelationships.length ? exposedRelationships.map((edge) => (
                  <div key={edge.relationship_id} className="rounded border border-slate-800 bg-slate-950 p-2 text-[11px]">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-slate-300">{edge.relationship_type}</span>
                      <span className={edge.inferred ? 'text-amber-400' : 'text-emerald-400'}>{edge.inferred ? 'inferred' : 'corroborated'}</span>
                    </div>
                    <div className="mt-1 truncate text-slate-500">{edge.from_node_id} → {edge.to_node_id}</div>
                    <div className="mt-1 text-slate-600">confidence {edge.confidence ?? 0}</div>
                  </div>
                )) : <div className="text-xs text-slate-500">No propagating relationships are available.</div>}
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-200">
                <ShieldCheck className="h-4 w-4 text-sky-400" /> Coverage gaps
              </div>
              <div className="space-y-2">
                {(payload?.coverage_gaps ?? []).map((gap) => (
                  <div key={gap.gap} className="rounded border border-slate-800 bg-slate-950 p-2 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-slate-300">{gap.gap.replaceAll('_', ' ')}</span>
                      <span className="font-mono text-slate-400">{gap.count ?? 0}</span>
                    </div>
                    {gap.note && <div className="mt-1 text-[11px] text-slate-600">{gap.note}</div>}
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <div className="mb-3 text-xs font-semibold text-slate-200">Incident and evidence timeline</div>
              <div className="max-h-80 space-y-2 overflow-y-auto">
                {timeline.length ? timeline.map((item, index) => (
                  <button
                    key={`${item.evidence_id}-${item.asset_id}-${index}`}
                    type="button"
                    onClick={() => setSelected(assets.find((asset) => asset.asset_id === item.asset_id) ?? null)}
                    className="block w-full rounded border border-slate-800 bg-slate-950 p-2 text-left"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <StatusBadge status={item.status} />
                      <span className="font-mono text-[10px] text-slate-600">{item.occurred_at?.slice(0, 19) || 'undated'}</span>
                    </div>
                    <div className="mt-1 truncate text-xs text-slate-300">{item.cause || item.evidence_id}</div>
                    <div className="mt-1 truncate font-mono text-[10px] text-slate-600">{item.asset_id}</div>
                  </button>
                )) : <div className="text-xs text-slate-500">No current impact evidence.</div>}
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-200">
                <AlertTriangle className="h-4 w-4 text-amber-400" /> Contradiction review
              </div>
              <div className="max-h-80 space-y-2 overflow-y-auto">
                {contradictions.length ? contradictions.map((entry) => (
                  <div key={entry.asset_id} className="rounded border border-amber-500/20 bg-amber-500/5 p-2">
                    <div className="font-mono text-[11px] text-amber-300">{entry.asset_id}</div>
                    <div className="mt-1 text-[11px] text-slate-400">
                      {entry.items.length} inactive, resolved, or rejected evidence item{entry.items.length === 1 ? '' : 's'} retained for adjudication.
                    </div>
                  </div>
                )) : <div className="text-xs text-slate-500">No contradictory evidence is currently linked.</div>}
              </div>
            </section>
          </div>

          <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-[11px] text-slate-500">
            Baseline <span className="font-mono text-slate-300">{payload?.baseline_id ?? 'unavailable'}</span> · shadow mode · no automatic control actions · no public notification activation · confirmation requires direct evidence, not confidence alone.
          </section>
        </div>
      )}

      <AssetDetail asset={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
