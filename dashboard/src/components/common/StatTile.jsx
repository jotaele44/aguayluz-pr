// Card-style KPI tile: optional icon, uppercase label, large mono value.
export default function StatTile({ icon: Icon, label, value, valueClass = 'text-slate-100' }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center gap-2 text-xs text-slate-400 font-mono uppercase tracking-wider mb-2">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        {label}
      </div>
      <p className={`text-2xl font-semibold font-mono ${valueClass}`}>{value}</p>
    </div>
  )
}
