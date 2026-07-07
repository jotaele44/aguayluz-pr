import { useMemo, useState } from 'react'
import { useAssetsGeojson, useEvents, useHealth, useReviewQueue, useSummary } from '@/lib/hooks'
import { Activity, AlertTriangle, Database, Droplets, MapPinned, ShieldCheck, WifiOff, X } from 'lucide-react'

function Kpi({ icon: Icon, label, value, hint, tone = 'text-slate-300', emphasis = false }) {
  return (
    <div className={`flex min-w-[132px] items-center gap-2 rounded-lg border px-3 py-2 shrink-0 ${emphasis ? 'border-sky-500/30 bg-sky-500/10' : 'border-slate-800 bg-slate-900/70'}`}>
      <Icon className={`h-4 w-4 ${tone}`} />
      <div className="min-w-0 leading-none">
        <div className="text-sm font-semibold text-slate-100">{value ?? '–'}</div>
        <div className="mt-1 text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
        {hint && <div className="mt-1 truncate text-[10px] text-slate-400">{hint}</div>}
      </div>
    </div>
  )
}

export default function StatsBar() {
  const { data: health, isError } = useHealth()
  const { data: assetsGeo } = useAssetsGeojson()
  const { data: events = [] } = useEvents()
  const { data: reviewQueue = [] } = useReviewQueue()
  const { data: summary } = useSummary()
  const [dismissed, setDismissed] = useState(false)

  const up = health?.status === 'ok'
  const c = health?.counts ?? {}
  const r = health?.readiness ?? {}

  const readingsCount = useMemo(() => {
    if (!c.readings) return null
    return Object.values(c.readings).reduce((total, n) => total + Number(n || 0), 0)
  }, [c.readings])

  const mapped = assetsGeo?.features?.length
  const coverage = r.coverage_pct != null ? `${r.coverage_pct}%` : '–'
  const reviewCount = r.records_review ?? reviewQueue.length
  const reviewTone = reviewCount > 0 ? 'text-amber-300' : 'text-emerald-300'
  const showDownBanner = (isError || (!up && health != null)) && !dismissed

  return (
    <div className="flex flex-col border-b border-slate-800 bg-slate-900/60">
      {showDownBanner && (
        <div className="flex items-center gap-2 px-4 py-1.5 bg-red-950/60 border-b border-red-800/40 text-red-300 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">Backend unreachable — data may be stale. Check <code className="font-mono">uvicorn server.backend.main:app --port 8000</code>.</span>
          <button onClick={() => setDismissed(true)} className="hover:text-red-100">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      <div className="flex items-center gap-2 px-4 py-2 overflow-x-auto">
        <div className="flex items-center gap-2 shrink-0 pr-1">
          <span className={`inline-flex h-2.5 w-2.5 rounded-full ${up ? 'bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,.65)]' : 'bg-red-400'}`} />
          <div className="leading-none">
            <div className="text-sm font-medium text-slate-100">Backend {up ? 'online' : 'down'}</div>
            <div className="mt-1 text-[10px] text-slate-500">FastAPI read layer · repo data</div>
          </div>
        </div>
        <div className="h-8 w-px bg-slate-800 shrink-0" />
        <Kpi icon={Database} label="Assets" value={c.assets} hint="canonical JSONL" tone="text-sky-300" emphasis />
        <Kpi icon={MapPinned} label="Mapped" value={mapped} hint="GeoJSON features" tone="text-cyan-300" />
        <Kpi icon={Activity} label="Events" value={c.events ?? events.length} hint="service records" tone="text-amber-300" />
        <Kpi icon={Droplets} label="Readings" value={readingsCount} hint="reservoir · generation · reliability" tone="text-blue-300" />
        <Kpi icon={ShieldCheck} label="Coverage" value={coverage} hint={r.module_status ? `readiness ${r.module_status}` : 'summary'} tone="text-emerald-300" />
        <Kpi icon={AlertTriangle} label="Review" value={reviewCount} hint="human adjudication" tone={reviewTone} />
        {summary?.sanitized_summary && (
          <span className="text-[11px] text-slate-500 shrink-0 max-w-xs truncate ml-2" title={summary.sanitized_summary}>
            {summary.sanitized_summary}
          </span>
        )}
        {!up && <Kpi icon={WifiOff} label="Fallback" value="cached" hint="API unavailable" tone="text-red-300" />}
      </div>
    </div>
  )
}
