import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, Database, LockKeyhole, ShieldCheck, Wheat } from 'lucide-react'
import { getFoodResilienceView } from '@/lib/food-resilience-api'

const STATE_TONE = {
  NORMAL: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  WATCH: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  ELEVATED: 'border-orange-500/30 bg-orange-500/10 text-orange-300',
  SEVERE: 'border-red-500/30 bg-red-500/10 text-red-300',
  CRITICAL: 'border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300',
  UNKNOWN: 'border-slate-700 bg-slate-900/60 text-slate-400',
}

function Tone({ state }) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${STATE_TONE[state] || STATE_TONE.UNKNOWN}`}>
      {state || 'UNKNOWN'}
    </span>
  )
}

function MetricLock({ title, phase, trackingIssue }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-start gap-3">
        <LockKeyhole className="mt-0.5 h-5 w-5 text-slate-400" />
        <div>
          <h3 className="font-semibold text-slate-100">{title}</h3>
          <p className="mt-1 text-xs uppercase tracking-wider text-slate-500">Phase {phase} · MODEL_UNAVAILABLE</p>
          <p className="mt-2 text-sm text-slate-400">
            This output remains inaccessible until its scientific promotion gates pass.
          </p>
          {trackingIssue && (
            <a className="mt-3 inline-block text-sm text-sky-400 hover:text-sky-300" href={trackingIssue} target="_blank" rel="noreferrer">
              Promotion gate record
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

export default function FoodResiliencePage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['food-resilience-view'],
    queryFn: getFoodResilienceView,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  if (isLoading) {
    return <div className="p-6 text-sm text-slate-400">Loading canonical food-resilience state…</div>
  }

  if (error || !data) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold text-slate-100">Food System Resilience</h1>
        <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
          Canonical food-resilience state is unavailable. No local substitute has been applied.
        </div>
      </div>
    )
  }

  const summary = data.summary || {}
  const signals = data.signals || []
  const baseline = data.baseline || {}
  const baselineRecords = baseline.records || []
  const trackingIssue = data.scenarios?.find((item) => item.tracking_issue)?.tracking_issue
  const availableSignals = signals.filter((item) => item.availability_state === 'AVAILABLE').length

  return (
    <div className="space-y-6 p-6" data-testid="food-resilience-page">
      <section className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-emerald-400">
            <Wheat className="h-4 w-4" />
            FOOD_SYSTEM_RESILIENCE
          </div>
          <h1 className="mt-2 text-3xl font-bold text-slate-100">Food System Resilience</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-400">
            Cross-sector warning and baseline evidence for Puerto Rico food-system resilience. Scientific state is computed upstream and projected read-only into this interface.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Tone state={summary.state} />
          <span className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-400">{summary.phase}</span>
        </div>
      </section>

      <section className="rounded-xl border border-sky-500/20 bg-sky-500/5 p-4" aria-label="Scientific projection invariant">
        <div className="flex gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-sky-400" />
          <div>
            <p className="font-medium text-slate-100">Scientific model → canonical state → deterministic GUI projection</p>
            <p className="mt-1 text-sm text-slate-400">The interface does not generate scientific truth, replace missing evidence, or unlock gated model outputs.</p>
          </div>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <p className="text-xs uppercase tracking-wider text-slate-500">Overall state</p>
          <div className="mt-3"><Tone state={summary.state} /></div>
          <p className="mt-3 text-xs text-slate-500">Trend: {summary.trend || 'UNKNOWN'}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <p className="text-xs uppercase tracking-wider text-slate-500">Activation</p>
          <p className="mt-2 text-lg font-semibold text-slate-100">Phase 1</p>
          <p className="mt-1 text-xs text-slate-500">Observable warning indicators</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <p className="text-xs uppercase tracking-wider text-slate-500">Evidence completeness</p>
          <p className="mt-2 text-lg font-semibold text-slate-100">{Math.round((summary.data_completeness || 0) * 100)}%</p>
          <p className="mt-1 text-xs text-slate-500">{availableSignals} of {signals.length} registered signals available</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <p className="text-xs uppercase tracking-wider text-slate-500">Confidence</p>
          <p className="mt-2 text-lg font-semibold text-slate-100">{summary.confidence || 'UNKNOWN'}</p>
          <p className="mt-1 text-xs text-slate-500">As of {summary.as_of ? new Date(summary.as_of).toLocaleString() : 'unknown'}</p>
        </div>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
          <Activity className="h-4 w-4 text-emerald-400" />
          <h2 className="font-semibold text-slate-100">Phase 1 — observable warning indicators</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[840px] text-left text-sm">
            <thead className="bg-slate-950/50 text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-3">Signal</th>
                <th className="px-4 py-3">Node</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Freshness</th>
                <th className="px-4 py-3">Observed</th>
                <th className="px-4 py-3">Value</th>
                <th className="px-4 py-3">Availability</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {signals.map((signal) => (
                <tr key={signal.signal_id} className="text-slate-300">
                  <td className="px-4 py-3 font-mono text-xs text-slate-300">{signal.signal_id}</td>
                  <td className="px-4 py-3">{signal.node_id}</td>
                  <td className="px-4 py-3"><Tone state={signal.state} /></td>
                  <td className="px-4 py-3 text-slate-400">{signal.freshness || 'UNKNOWN'}</td>
                  <td className="px-4 py-3 text-slate-400">{signal.observed_date || '—'}</td>
                  <td className="px-4 py-3">{signal.value == null ? '—' : `${signal.value}${signal.unit ? ` ${signal.unit}` : ''}`}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">{signal.availability_state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
          <Database className="h-4 w-4 text-sky-400" />
          <h2 className="font-semibold text-slate-100">Phase 2 — Vector A baseline ledger</h2>
        </div>
        <div className="p-4">
          <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-sm text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>
              Current operational food-supply arithmetic is not yet reconciled. Structural and historical records remain explicitly separated by reference period and analytical role.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {baselineRecords.map((record) => (
              <div key={record.metric_id} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                <p className="font-mono text-xs text-slate-500">{record.metric_id}</p>
                <p className="mt-2 text-xl font-semibold text-slate-100">{record.value} <span className="text-sm font-normal text-slate-500">{record.unit}</span></p>
                <p className="mt-2 text-xs text-slate-400">Reference: {record.reference_period}</p>
                <p className="mt-1 text-xs text-slate-500">{record.role} · {record.evidence_state}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-2">
            {(baseline.current_ledger_sources || []).map((source) => (
              <div key={source.source_id} className="flex flex-col gap-1 rounded-lg border border-slate-800 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
                <span className="font-mono text-xs text-slate-300">{source.source_id}</span>
                <span className="text-slate-500">{source.reference_period} · {source.state}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <h2 className="mb-3 font-semibold text-slate-100">Scientific promotion locks</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <MetricLock title="Dynamic scenario estimates" phase={3} trackingIssue={trackingIssue} />
          <MetricLock title="Robust food-resilience monitoring" phase={4} trackingIssue={trackingIssue} />
        </div>
      </section>
    </div>
  )
}
