import { useHealth } from '@/lib/hooks'
import { Zap, Droplets, Activity, ShieldCheck } from 'lucide-react'

function Kpi({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 px-3 py-1.5 shrink-0">
      <Icon className="h-4 w-4 text-slate-400" />
      <div className="leading-none">
        <div className="text-sm font-semibold text-slate-100">{value}</div>
        <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      </div>
    </div>
  )
}

export default function StatsBar() {
  const { data: health } = useHealth()
  const up = health?.status === 'ok'
  const c = health?.counts ?? {}
  const r = health?.readiness ?? {}

  return (
    <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-800 bg-slate-900/60 overflow-x-auto">
      <div className="flex items-center gap-2 shrink-0">
        <span className={`inline-flex h-2.5 w-2.5 rounded-full ${up ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
        <span className="text-sm font-medium text-slate-200">Backend {up ? 'online' : 'down'}</span>
      </div>
      <div className="h-5 w-px bg-slate-800 shrink-0" />
      <Kpi icon={Zap} label="Assets" value={c.assets ?? '–'} />
      <Kpi icon={Activity} label="Events" value={c.events ?? '–'} />
      <Kpi icon={Droplets} label="Readings" value={c.readings ? Object.values(c.readings).reduce((a, b) => a + b, 0) : '–'} />
      <Kpi icon={ShieldCheck} label="Coverage" value={r.coverage_pct != null ? `${r.coverage_pct}%` : '–'} />
      {r.module_status && (
        <span className="text-[11px] text-slate-400 shrink-0">
          readiness <span className={r.module_status === 'PASS' ? 'text-emerald-300' : 'text-amber-300'}>{r.module_status}</span>
          {r.records_review != null && ` · ${r.records_review} in review`}
        </span>
      )}
    </div>
  )
}
