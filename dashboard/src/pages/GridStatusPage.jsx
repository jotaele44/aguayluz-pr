import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, Database, Gauge, History, ShieldCheck, Zap } from 'lucide-react'

import PageHeader from '@/components/common/PageHeader'
import { getGridStatus } from '@/lib/api'

const METRICS = [
  ['customers_without_service', 'Customers without service', 'customers'],
  ['demand_mw', 'Reported demand', 'MW'],
  ['available_supply_mw', 'Available supply', 'MW'],
  ['reserve_mw', 'Reserves', 'MW'],
  ['hydro_available_mw', 'Hydroelectric availability', 'MW'],
]
const label = (v) => v == null ? 'Unavailable' : String(v)
const iso = (v) => v ? new Date(v).toLocaleString('en-PR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Puerto_Rico' }) : 'No verified date'

function MetricCard({ field, name, unit, data }) {
  const value = data?.measurements?.[field]
  return <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4" data-testid={`grid-metric-${field}`}>
    <p className="text-xs font-medium text-slate-400">{name}</p>
    <p className="mt-2 text-xl font-semibold text-slate-100">{label(value)}</p>
    <p className="mt-1 text-xs text-slate-500">{value == null ? 'No qualified measurement' : unit}</p>
  </div>
}

export default function GridStatusPage() {
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ['grid/status/v1'],
    queryFn: getGridStatus,
    refetchInterval: 60_000,
    retry: false,
  })
  const status = error ? 'SOURCE_UNAVAILABLE' : data?.status ?? 'UNVERIFIED'
  return <section className="min-h-full space-y-6 pb-8">
    <PageHeader title="Electric Grid Monitor" subtitle="Puerto Rico · Evidence-first electricity observations">
      <button type="button" onClick={() => refetch()} className="rounded-md border border-slate-700 px-3 py-2 text-xs text-slate-200 hover:bg-slate-800">
        {isFetching ? 'Checking…' : 'Refresh observations'}
      </button>
    </PageHeader>
    <div className="space-y-5 px-6">
      <div role="status" className="flex items-start gap-3 rounded-xl border border-amber-700/50 bg-amber-950/20 p-4">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" aria-hidden="true" />
        <div>
          <div className="font-semibold text-amber-200">{isPending ? 'Checking source…' : status.replaceAll('_', ' ')}</div>
          <p className="mt-1 text-sm text-slate-300">
            {error ? 'The grid-status API could not be reached. No live status is inferred.' :
             'This alpha displays qualified evidence availability, not a certified real-time view of the grid.'}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {METRICS.map(([field, name, unit]) => <MetricCard key={field} field={field} name={name} unit={unit} data={data} />)}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <article className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
          <h2 className="flex items-center gap-2 font-semibold text-slate-100"><Database className="h-4 w-4" /> Source provenance</h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div><dt className="text-slate-400">Source family</dt><dd className="text-slate-200">{data?.source?.family ?? 'Unknown'}</dd></div>
            <div><dt className="text-slate-400">Most recent source observation</dt><dd className="text-slate-200">{iso(data?.source?.observation_at)}</dd></div>
            <div><dt className="text-slate-400">Captured snapshots</dt><dd className="text-slate-200">{data?.source?.snapshot_count ?? 'Unknown'}</dd></div>
            <div><dt className="text-slate-400">Source schema state</dt><dd className="text-amber-200">{data?.source?.schema_state ?? 'UNVERIFIED'}</dd></div>
            <div><dt className="text-slate-400">Original-payload SHA-256</dt><dd className="break-all font-mono text-xs text-slate-200">{data?.source?.payload_sha256 ?? 'Not available'}</dd></div>
          </dl>
        </article>
        <article className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
          <h2 className="flex items-center gap-2 font-semibold text-slate-100"><ShieldCheck className="h-4 w-4" /> Evidence gates</h2>
          <ul className="mt-4 space-y-2 text-sm text-slate-300">
            {(data?.limitations ?? [
              'Source data is not available.',
              'No live operating conditions may be inferred.',
            ]).map((item) => <li key={item} className="flex items-start gap-2"><span aria-hidden="true" className="text-amber-400">•</span>{item}</li>)}
          </ul>
          <p className="mt-5 border-t border-slate-800 pt-4 text-xs font-medium text-amber-300">
            Production certification: WITHHELD · No unverified grid operations are shown.
          </p>
        </article>
      </div>
      <nav aria-label="Related grid evidence" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Link to="/outages" className="rounded-lg border border-slate-800 p-4 text-sm text-sky-300 hover:border-sky-600"><History className="mb-2 h-4 w-4" /> Outage history</Link>
        <Link to="/source-intelligence" className="rounded-lg border border-slate-800 p-4 text-sm text-sky-300 hover:border-sky-600"><Gauge className="mb-2 h-4 w-4" /> Source intelligence</Link>
        <Link to="/map" className="rounded-lg border border-slate-800 p-4 text-sm text-sky-300 hover:border-sky-600"><Zap className="mb-2 h-4 w-4" /> Infrastructure map</Link>
      </nav>
    </div>
  </section>
}
