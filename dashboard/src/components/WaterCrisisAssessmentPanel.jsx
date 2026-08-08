import { Badge } from '@/components/ui/badge'

// Design-only and intentionally unwired. The parent alert detail page must pass a
// validated candidate extension explicitly; no fetch, polling, reload, or intake is
// activated here.
export default function WaterCrisisAssessmentPanel({ assessment }) {
  if (!assessment) return null
  const causes = assessment.likely_causes ?? []
  const contradictions = assessment.contradictions ?? []
  const mitigation = assessment.recommended_immediate_mitigation ?? []
  const restoration = assessment.restoration_criteria ?? []

  return (
    <section data-testid="water-crisis-assessment" className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-slate-100">Water-crisis assessment</h2>
        <Badge variant="outline">{assessment.assessment_code}</Badge>
        <Badge variant="outline">{assessment.operational_state}</Badge>
        <Badge variant="outline">{assessment.official_vs_derived}</Badge>
        <Badge variant="outline">candidate only</Badge>
      </div>
      <dl className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
        <div><dt className="text-slate-500">Municipalities</dt><dd className="text-slate-200">{(assessment.affected_municipalities ?? []).join(', ')}</dd></div>
        <div><dt className="text-slate-500">Validity</dt><dd className="text-slate-200">{assessment.observed_at} — {assessment.valid_until}</dd></div>
      </dl>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div><h3 className="text-xs font-semibold text-slate-400">Likely causes</h3><ul className="mt-1 space-y-1 text-xs text-slate-300">{causes.map((x, i) => <li key={i}>{x.cause} · {x.confidence}/100</li>)}</ul></div>
        <div><h3 className="text-xs font-semibold text-slate-400">Contradictions</h3><ul className="mt-1 space-y-1 text-xs text-slate-300">{contradictions.map((x, i) => <li key={i}>{x.claim_a} ↔ {x.claim_b} · {x.status}</li>)}</ul></div>
        <div><h3 className="text-xs font-semibold text-slate-400">Restoration criteria</h3><ul className="mt-1 space-y-1 text-xs text-slate-300">{restoration.map((x, i) => <li key={i}>{x.criterion} · {x.state}</li>)}</ul></div>
        <div><h3 className="text-xs font-semibold text-slate-400">Immediate mitigation</h3><ul className="mt-1 space-y-1 text-xs text-slate-300">{mitigation.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
      </div>
    </section>
  )
}
