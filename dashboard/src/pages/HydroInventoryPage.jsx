import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Droplet, GitCompare, Layers, MapPinOff, Scale, Waves } from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import Panel from '@/components/common/Panel'
import PanelState from '@/components/common/PanelState'
import { Button } from '@/components/ui/button'
import {
  useHydroCandidates, useHydroConflicts, useHydroFeature, useHydroFeatures, useHydroSummary,
} from '@/lib/hydro-inventory-hooks'
import { cn } from '@/lib/utils'

const FALLBACK_SCOPE = 'Every aquifer, well, spring, stream and waterbody the enumerated public sources describe, reconciled across sources. Name and distance matches are listed as candidates, never merged.'
const SECTIONS = [
  { key: 'aquifers', label: 'Aquifers' },
  { key: 'wells', label: 'Wells' },
  { key: 'springs', label: 'Springs' },
  { key: 'surface', label: 'Surface water' },
  { key: 'conflicts', label: 'Conflicts' },
  { key: 'candidates', label: 'Candidates' },
  { key: 'sources', label: 'Sources & coverage' },
]
const STATE_LABEL = {
  MONITORED_NOW: 'Monitored now',
  HISTORICAL_ONLY: 'Historical only',
  NO_DATA: 'No readings',
  READINGS_ABSENT_ON_SERVER: 'Readings not on this server',
}
const STATE_TONE = {
  MONITORED_NOW: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  HISTORICAL_ONLY: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  NO_DATA: 'border-slate-600 bg-slate-800/60 text-slate-300',
  READINGS_ABSENT_ON_SERVER: 'border-slate-600 bg-slate-800/60 text-slate-400',
}
const SOURCE_LABEL = {
  usgs_ha730_aquifers_pr: 'USGS HA 730-N map',
  usgs_aquifer_codes: 'USGS aquifer code',
  usgs_national_aquifer_codes: 'USGS national aquifer',
  usgs_ha730_text: 'USGS HA 730-N text',
  drna_pira_2016: 'DRNA PIRA 2016',
  usgs_monitoring_locations: 'USGS',
  wqp_wells: 'Water Quality Portal',
  epa_sdwis_wells: 'EPA SDWIS',
  wqp_springs: 'Water Quality Portal',
  usgs_gnis_names: 'USGS GNIS',
  usgs_nhd_flowlines: 'USGS NHD',
  usgs_nhd_waterbodies: 'USGS NHD',
  usgs_wbd: 'USGS WBD',
  epa_sdwis_intakes: 'EPA SDWIS',
  noaa_nwps_gauges: 'NOAA NWS',
  repo_utility_assets: 'Repository assets',
}
const SURFACE_TYPES = [
  ['stream', 'Stream reaches'], ['watercourse', 'Named watercourses'], ['waterfall', 'Waterfalls'],
  ['waterbody', 'Waterbodies'], ['reservoir', 'Reservoirs'], ['intake', 'Intakes'], ['gauge', 'Gauges'],
  ['watershed', 'Watersheds'],
]
const detailFor = (f) => {
  switch (f.feature_type) {
    case 'well':
    case 'spring': return f.aquifer_code ? `USGS aquifer code ${f.aquifer_code}` : ''
    case 'stream': return [f.flow_type, f.lengthkm != null ? `${f.lengthkm} km` : null, f.huc8 ? `HUC8 ${f.huc8}` : null].filter(Boolean).join(' · ')
    case 'watercourse': return `${f.reaches ?? 0} mapped reaches${f.gnis_class ? ` · ${f.gnis_class}` : ''}`
    case 'waterbody':
    case 'reservoir': return [f.water_type, f.areasqkm != null ? `${f.areasqkm} km²` : null].filter(Boolean).join(' · ')
    case 'gauge': return [f.site_type_code ? `USGS ${f.site_type_code}` : null, f.nws_lid ? `NWS ${f.nws_lid}` : null].filter(Boolean).join(' · ')
    case 'intake': return f.activity === 'A' ? 'active' : f.activity === 'I' ? 'inactive' : ''
    case 'watershed': return `${(f.level ?? '').toUpperCase()} ${f.huc ?? ''}`
    default: return ''
  }
}
const PAGE = 50
const range = (cov) => (cov ? (cov.features_lower === cov.features_upper ? `${cov.features_upper}` : `${cov.features_lower}–${cov.features_upper}`) : '—')
const sourceLabel = (key) => SOURCE_LABEL[key] ?? key

function Badge({ className, children }) {
  return <span className={cn('inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium', className)}>{children}</span>
}

function Tiles({ summary }) {
  const aq = summary?.coverage?.aquifer
  const wl = summary?.coverage?.well
  const sp = summary?.coverage?.spring
  const cov = summary?.coverage ?? {}
  const unplaced = Object.values(cov).reduce((n, c) => n + (c?.unlocated ?? 0), 0)
  const lakes = (cov.waterbody?.features_upper ?? 0) + (cov.reservoir?.features_upper ?? 0)
  const tiles = [
    { label: 'Aquifers (range)', value: range(aq), icon: Layers, testid: 'tile-aquifers' },
    { label: 'Wells (range)', value: range(wl), icon: Waves, testid: 'tile-wells' },
    { label: 'Springs (range)', value: range(sp), icon: Droplet, testid: 'tile-springs' },
    { label: 'Stream reaches', value: range(cov.stream), icon: Waves, testid: 'tile-streams' },
    { label: 'Waterbodies & reservoirs', value: summary?.coverage ? lakes : '—', icon: Droplet, testid: 'tile-lakes' },
    { label: 'Listed, not placed (no coordinates)', value: summary?.coverage ? unplaced : '—', icon: MapPinOff, testid: 'tile-unlocated' },
    { label: 'Source disagreements', value: summary?.conflicts ?? '—', icon: Scale, testid: 'tile-conflicts' },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
      {tiles.map(({ label, value, icon: Icon, testid }) => (
        <div key={label} data-testid={testid} className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500"><Icon className="h-4 w-4" aria-hidden="true" />{label}</div>
          <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
        </div>
      ))}
    </div>
  )
}

function FeatureDetail({ id, onClose }) {
  const query = useHydroFeature(id)
  const data = query.data
  return (
    <Panel>
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Feature detail</h2>
        <Button size="sm" variant="outline" onClick={onClose} className="h-7 border-slate-700 bg-slate-950 text-xs text-slate-300">Close detail</Button>
      </div>
      <PanelState isLoading={query.isLoading} isError={query.isError} errorText={`Feature unavailable: ${String(query.error?.message ?? query.error)}`} isEmpty={!data} emptyText="No detail.">
        {data && (
          <div className="mt-3 space-y-3 text-xs" data-testid="feature-detail">
            <div>
              <div className="text-sm font-semibold text-slate-100">{data.feature.display_name}</div>
              <div className="font-mono text-[11px] text-slate-500">{data.feature.feature_id}</div>
              {data.feature.monitoring && <Badge className={cn('mt-1', STATE_TONE[data.feature.monitoring.state])}>{STATE_LABEL[data.feature.monitoring.state]}{data.feature.monitoring.last_observed_date ? ` · ${data.feature.monitoring.last_observed_date}` : ''}</Badge>}
              {data.feature.feature_type === 'aquifer' && <p className="mt-1 text-[11px] text-slate-400">Wells: {data.member_wells.authoritative} assigned by a USGS aquifer code, {data.member_wells.polygon_only} only inside the mapped outline.</p>}
            </div>
            <div>
              <div className="mb-1 font-medium text-slate-300">What each source says ({data.claims.length})</div>
              <ul className="space-y-1">
                {data.claims.map((c) => (
                  <li key={c.claim_id} className="rounded border border-slate-800 bg-slate-950/60 p-2">
                    <div className="flex flex-wrap items-center gap-2"><Badge className="border-slate-600 text-slate-300">{sourceLabel(c.source_key)}</Badge><span className="text-slate-200">{c.name_raw ?? '(no name)'}</span><span className="text-slate-500">{c.evidence_tier} · {c.extraction_method}</span></div>
                    <div className="mt-1 font-mono text-[10px] text-slate-500">{c.source_feature_id} · {c.lat != null ? `${c.lat}, ${c.lon}` : 'no location published'} · sha256 {c.manifestation_sha256.slice(0, 12)}…</div>
                  </li>
                ))}
              </ul>
            </div>
            {data.links.length > 0 && (
              <div>
                <div className="mb-1 font-medium text-slate-300">Links ({data.links.length})</div>
                <ul className="space-y-0.5 text-[11px] text-slate-400">
                  {data.links.slice(0, 40).map((lk) => <li key={lk.link_id}><span className="font-mono">{lk.link_type}</span> → <span className="font-mono text-slate-300">{lk.from === id ? lk.to : lk.from}</span> <span className="text-slate-500">({lk.edge_class}{lk.identity_tier ? `, ${lk.identity_tier}` : ''})</span></li>)}
                </ul>
              </div>
            )}
            {data.conflicts.length > 0 && (
              <div role="note" aria-label="Disagreements about this feature" className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-amber-100/90">
                {data.conflicts.map((c) => <div key={c.conflict_id}>{c.attribute}: {c.values_by_claim.length} sources disagree</div>)}
              </div>
            )}
          </div>
        )}
      </PanelState>
    </Panel>
  )
}

function AquiferTable({ onSelect }) {
  const query = useHydroFeatures({ type: 'aquifer', limit: 1000 })
  // Largest first: wells assigned by code, then wells inside the outline, then mapped area.
  const items = useMemo(() => [...(query.data?.items ?? [])].sort((a, b) => (
    (b.member_wells?.AUTHORITATIVE ?? 0) - (a.member_wells?.AUTHORITATIVE ?? 0)
    || (b.member_wells?.DERIVED_TOPOLOGICAL ?? 0) - (a.member_wells?.DERIVED_TOPOLOGICAL ?? 0)
    || (b.area_km2 ?? 0) - (a.area_km2 ?? 0)
  )), [query.data])
  return (
    <PanelState isLoading={query.isLoading} isError={query.isError} errorText={`Aquifers unavailable: ${String(query.error?.message ?? query.error)}`} isEmpty={!items.length} emptyText="No aquifers in the inventory yet.">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] text-left text-xs" aria-label="Aquifers">
          <thead className="text-[11px] uppercase tracking-wide text-slate-500">
            <tr className="border-b border-slate-800">
              <th className="py-2 pr-3 font-medium">Aquifer</th><th className="py-2 pr-3 font-medium">Source</th>
              <th className="py-2 pr-3 font-medium">Island / municipios</th><th className="py-2 pr-3 text-right font-medium">Area km²</th>
              <th className="py-2 pr-3 text-right font-medium">Wells by code</th><th className="py-2 pr-3 text-right font-medium">Wells in outline</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f) => (
              <tr key={f.feature_id} className="cursor-pointer border-b border-slate-900 hover:bg-slate-900/60" onClick={() => onSelect(f.feature_id)} data-testid={`aquifer-${f.feature_id}`}>
                <th scope="row" className="py-1.5 pr-3 font-medium text-slate-200">
                  <button type="button" className="text-left hover:underline" onClick={(e) => { e.stopPropagation(); onSelect(f.feature_id) }}>{f.display_name}</button>
                  {f.name_is_source_class_only && <div className="text-[10px] font-normal text-slate-500">unnamed in the source; labelled by location</div>}
                  <div className="font-mono text-[10px] font-normal text-slate-500">{f.feature_id}</div>
                </th>
                <td className="py-1.5 pr-3 text-slate-400">{sourceLabel(f.sources[0])}</td>
                <td className="py-1.5 pr-3 text-slate-400">{[f.island, (f.municipios ?? []).slice(0, 3).join(', ')].filter(Boolean).join(' · ') || f.system || '—'}</td>
                <td className="py-1.5 pr-3 text-right text-slate-300">{f.area_km2 ?? '—'}</td>
                <td className="py-1.5 pr-3 text-right text-slate-300">{f.member_wells?.AUTHORITATIVE ?? 0}</td>
                <td className="py-1.5 pr-3 text-right text-slate-300">{f.member_wells?.DERIVED_TOPOLOGICAL ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelState>
  )
}

const POINT_SOURCES = {
  well: [['', 'All sources'], ['usgs_monitoring_locations', 'USGS'], ['wqp_wells', 'Water Quality Portal'], ['epa_sdwis_wells', 'EPA SDWIS']],
  spring: [['', 'All sources'], ['usgs_monitoring_locations', 'USGS'], ['usgs_gnis_names', 'USGS GNIS']],
}

function WellTable({ onSelect, type = 'well', label = 'Wells' }) {
  const sourceOptions = POINT_SOURCES[type] ?? null
  const [q, setQ] = useState('')
  const [source, setSource] = useState('')
  const [offset, setOffset] = useState(0)
  const params = useMemo(() => ({ type, q: q || undefined, source: source || undefined, limit: PAGE, offset }), [type, q, source, offset])
  const query = useHydroFeatures(params)
  const items = query.data?.items ?? []
  const total = query.data?.total ?? 0
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input aria-label={`Search ${label.toLowerCase()}`} value={q} onChange={(e) => { setQ(e.target.value); setOffset(0) }} placeholder="Search name or id" className="h-8 w-56 rounded border border-slate-700 bg-slate-950 px-2 text-xs text-slate-200" />
        <div role="group" aria-label="Source" className="flex flex-wrap gap-1">
          {(sourceOptions ?? []).map(([key, text]) => (
            <Button key={key || 'all'} size="sm" variant="outline" aria-pressed={source === key} onClick={() => { setSource(key); setOffset(0) }} className={cn('h-7 border-slate-700 bg-slate-950 text-xs', source === key ? 'border-sky-500/60 text-sky-200' : 'text-slate-400')}>{text}</Button>
          ))}
        </div>
        <span className="text-[11px] text-slate-500">{total} {label.toLowerCase()}</span>
      </div>
      <PanelState isLoading={query.isLoading} isError={query.isError} errorText={`${label} unavailable: ${String(query.error?.message ?? query.error)}`} isEmpty={!items.length} emptyText={`No ${label.toLowerCase()} match.`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-xs" aria-label={label}>
            <thead className="text-[11px] uppercase tracking-wide text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-3 font-medium">Name</th><th className="py-2 pr-3 font-medium">Sources</th>
                <th className="py-2 pr-3 font-medium">Details</th><th className="py-2 pr-3 font-medium">Location</th>
                {type === 'well' && <th className="py-2 pr-3 font-medium">Monitoring</th>}
              </tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.feature_id} className="border-b border-slate-900" data-testid={`${type}-row`}>
                  <th scope="row" className="py-1.5 pr-3 font-medium text-slate-200">
                    <button type="button" className="text-left hover:underline" onClick={() => onSelect(f.feature_id)}>{f.display_name ?? '(no name)'}</button>
                    <div className="font-mono text-[10px] font-normal text-slate-500">{f.feature_id}</div>
                  </th>
                  <td className="py-1.5 pr-3 text-slate-400">{f.sources.map(sourceLabel).join(' + ')}</td>
                  <td className="py-1.5 pr-3 text-slate-300">{detailFor(f) || '—'}</td>
                  <td className="py-1.5 pr-3 text-slate-400">{f.located === false ? 'not published by the source' : f.lat != null ? `${f.lat}, ${f.lon}` : 'polygon'}{f.huc10 ? ` · HUC10 ${f.huc10}` : ''}</td>
                  {type === 'well' && <td className="py-1.5 pr-3">{f.monitoring && <Badge className={STATE_TONE[f.monitoring.state]}>{STATE_LABEL[f.monitoring.state]}</Badge>}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex items-center gap-2 text-[11px] text-slate-500">
          <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="h-7 border-slate-700 bg-slate-950 text-xs text-slate-300">Previous</Button>
          <span>{total ? `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}` : ''}</span>
          <Button size="sm" variant="outline" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} className="h-7 border-slate-700 bg-slate-950 text-xs text-slate-300">Next</Button>
        </div>
      </PanelState>
    </>
  )
}

function SurfaceSection({ onSelect }) {
  const [type, setType] = useState('stream')
  const label = SURFACE_TYPES.find(([key]) => key === type)?.[1] ?? type
  return (
    <>
      <div role="group" aria-label="Surface feature type" className="mb-3 flex flex-wrap gap-1">
        {SURFACE_TYPES.map(([key, text]) => (
          <Button key={key} size="sm" variant="outline" aria-pressed={type === key} onClick={() => setType(key)} className={cn('h-7 border-slate-700 bg-slate-950 text-xs', type === key ? 'border-sky-500/60 text-sky-200' : 'text-slate-400')}>{text}</Button>
        ))}
      </div>
      <WellTable key={type} onSelect={onSelect} type={type} label={label} />
    </>
  )
}

function ConflictList() {
  const query = useHydroConflicts()
  const items = query.data?.items ?? []
  return (
    <PanelState isLoading={query.isLoading} isError={query.isError} errorText={`Conflicts unavailable: ${String(query.error?.message ?? query.error)}`} isEmpty={!items.length} emptyText="No source disagreements recorded.">
      <ul className="space-y-2 text-xs" aria-label="Source disagreements">
        {items.map((c) => (
          <li key={c.conflict_id} className="rounded border border-slate-800 bg-slate-950/60 p-3" data-testid="conflict">
            <div className="flex flex-wrap items-center gap-2"><span className="font-medium text-slate-200">{c.attribute.replaceAll('_', ' ')}</span><Badge className={c.resolution === 'UNRESOLVED_SHOWN' ? 'border-amber-500/40 text-amber-300' : 'border-sky-500/40 text-sky-300'}>{c.resolution === 'UNRESOLVED_SHOWN' ? 'unresolved, shown' : 'resolved by measured fit'}</Badge><span className="text-slate-500">{c.kind}</span></div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-400">
              {c.values_by_claim.map((v, i) => <li key={i}><span className="text-slate-300">{sourceLabel(v.source_key)}</span>: {Array.isArray(v.value) ? v.value.join(', ') : v.value}{v.coastline_median_m != null ? ` (coastline median ${v.coastline_median_m} m)` : ''}</li>)}
            </ul>
            {c.note && <p className="mt-1 text-[11px] text-slate-500">{c.note}</p>}
          </li>
        ))}
      </ul>
    </PanelState>
  )
}

function CandidateList({ onSelect }) {
  const query = useHydroCandidates({ tier: 'I4' })
  const items = query.data?.items ?? []
  return (
    <PanelState isLoading={query.isLoading} isError={query.isError} errorText={`Candidates unavailable: ${String(query.error?.message ?? query.error)}`} isEmpty={!items.length} emptyText="No candidate matches.">
      <p className="mb-2 text-[11px] text-slate-500">Possible same-feature pairs from different sources. None is merged: a name and a distance are not identity. Only these narrow the count range.</p>
      <ul className="space-y-1 text-xs" aria-label="Candidate matches">
        {items.map((lk) => (
          <li key={lk.link_id} className="flex flex-wrap items-center gap-2 rounded border border-slate-800 bg-slate-950/60 p-2" data-testid="candidate">
            <button type="button" className="text-slate-200 hover:underline" onClick={() => onSelect(lk.from)}>{lk.from_name}</button>
            <span className="text-slate-500">≟</span>
            <button type="button" className="text-slate-200 hover:underline" onClick={() => onSelect(lk.to)}>{lk.to_name}</button>
            <span className="text-slate-500">{lk.evidence_classes.join(' + ').toLowerCase().replaceAll('_', ' ')}{lk.distance_m != null ? ` · ${lk.distance_m} m` : ''}</span>
          </li>
        ))}
      </ul>
    </PanelState>
  )
}

function SourcesPanel({ summary }) {
  const ledgers = Object.entries(summary?.source_ledgers ?? {})
  const datum = summary?.datum
  return (
    <div className="space-y-4 text-xs" data-testid="hydro-sources">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left" aria-label="Source ledgers">
          <thead className="text-[11px] uppercase tracking-wide text-slate-500">
            <tr className="border-b border-slate-800"><th className="py-2 pr-3 font-medium">Source</th><th className="py-2 pr-3 text-right font-medium">Rows</th><th className="py-2 pr-3 text-right font-medium">Assigned</th><th className="py-2 pr-3 font-medium">Excluded</th><th className="py-2 pr-3 font-medium">Closes</th></tr>
          </thead>
          <tbody>
            {ledgers.map(([key, l]) => (
              <tr key={key} className="border-b border-slate-900">
                <th scope="row" className="py-1.5 pr-3 font-medium text-slate-200">{sourceLabel(key)}</th>
                <td className="py-1.5 pr-3 text-right text-slate-300">{l.source}</td>
                <td className="py-1.5 pr-3 text-right text-slate-300">{l.assigned_to_features}</td>
                <td className="py-1.5 pr-3 text-slate-400">{Object.entries(l.excluded_by_reason).map(([r, n]) => `${n} ${r}`).join('; ') || '—'}</td>
                <td className="py-1.5 pr-3 text-slate-300">{l.state}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {datum && (
        <p className="text-slate-400">Aquifer map datum: the file declares NAD27, which puts the island {datum.checks?.declared_nad27?.median_north_offset_m} m north of the coastline; read as {datum.used} it fits to a median of {datum.checks?.puerto_rico_1940?.median_m} m. The map is drawn with the datum that fits.</p>
      )}
      <div>
        <div className="font-medium text-slate-300">Not enumerated yet</div>
        <p className="text-slate-400">{(summary?.phase_scope?.feature_types_not_enumerated ?? []).join(', ')}</p>
      </div>
      <div>
        <div className="font-medium text-slate-300">Known gaps</div>
        <ul className="list-disc pl-5 text-slate-400">{(summary?.open_residue ?? []).map((r) => <li key={r}>{r}</li>)}</ul>
      </div>
    </div>
  )
}

export default function HydroInventoryPage() {
  const summaryQuery = useHydroSummary()
  const summary = summaryQuery.data
  const [section, setSection] = useState('aquifers')
  const [selected, setSelected] = useState(null)
  const readingsPresent = summary?.monitoring?.readings_present

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Hydro Inventory" subtitle="Puerto Rico aquifers, wells, springs, streams, waterbodies, intakes and gauges, reconciled across every enumerated source" />
      <div className="min-h-0 flex-1 space-y-5 overflow-auto p-6">
        <ErrorBoundary label="Hydrologic inventory">
          <div role="note" aria-label="Hydro inventory scope" className="flex items-start gap-3 rounded-lg border border-sky-500/30 bg-sky-500/10 p-4">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" aria-hidden="true" />
            <div className="space-y-1 text-sm text-sky-100/90">
              <p>{summary?.scope?.statement ?? FALLBACK_SCOPE}</p>
              <p className="text-xs text-sky-200/80">
                Readings: <Link className="underline hover:text-sky-100" to="/monitoring">Monitoring</Link> (filter groundwater by aquifer) ·{' '}
                <Link className="underline hover:text-sky-100" to="/aquifer-bands">Aquifer Bands</Link> ·{' '}
                <Link className="underline hover:text-sky-100" to="/water-use">Water Use</Link>
              </p>
            </div>
          </div>

          <PanelState isLoading={summaryQuery.isLoading} isError={summaryQuery.isError}
            errorText={(
              <div className="space-y-2">
                <div>Inventory unavailable: {String(summaryQuery.error?.message ?? summaryQuery.error)}</div>
                <Button size="sm" variant="outline" onClick={() => summaryQuery.refetch()} className="h-7 border-slate-700 bg-slate-950 text-xs text-slate-300">Retry inventory</Button>
              </div>
            )}
            isEmpty={!summary?.coverage} emptyText="The inventory has not been built yet. It is produced by scripts/build_hydro_inventory.py.">
            <Tiles summary={summary} />
            {readingsPresent === false && (
              <p className="mt-2 text-[11px] text-slate-500">This server holds no reading files, so no well is shown as monitored. That is a property of this server, not of the wells.</p>
            )}
          </PanelState>

          <div role="group" aria-label="Inventory section" className="flex flex-wrap gap-1">
            {SECTIONS.map((s) => (
              <Button key={s.key} size="sm" variant="outline" aria-pressed={section === s.key} onClick={() => setSection(s.key)} className={cn('h-8 border-slate-700 bg-slate-950 text-xs', section === s.key ? 'border-sky-500/60 text-sky-200' : 'text-slate-400')}>{s.label}</Button>
            ))}
          </div>

          <div className={cn('grid gap-4', selected && 'xl:grid-cols-[minmax(0,1fr)_420px]')}>
            <Panel>
              {section === 'aquifers' && <AquiferTable onSelect={setSelected} />}
              {section === 'wells' && <WellTable onSelect={setSelected} />}
              {section === 'springs' && <WellTable key="springs" onSelect={setSelected} type="spring" label="Springs" />}
              {section === 'surface' && <SurfaceSection onSelect={setSelected} />}
              {section === 'conflicts' && <ConflictList />}
              {section === 'candidates' && <CandidateList onSelect={setSelected} />}
              {section === 'sources' && <SourcesPanel summary={summary} />}
            </Panel>
            {selected && <FeatureDetail id={selected} onClose={() => setSelected(null)} />}
          </div>
          <p className="flex items-center gap-1.5 text-[11px] text-slate-500"><GitCompare className="h-3.5 w-3.5" aria-hidden="true" /> Counts are ranges: the high figure keeps every candidate pair apart, the low figure merges them.</p>
        </ErrorBoundary>
      </div>
    </div>
  )
}
