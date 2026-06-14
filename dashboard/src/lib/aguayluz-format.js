// AguaYLuz-PR display helpers.

const TYPE = {
  power: { label: 'Power', hex: '#f59e0b', badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  water: { label: 'Water', hex: '#38bdf8', badge: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  wastewater: { label: 'Wastewater', hex: '#10b981', badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  telecom: { label: 'Telecom', hex: '#a78bfa', badge: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
  fuel: { label: 'Fuel', hex: '#fb7185', badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
}
export function typeMeta(t) {
  return TYPE[t] ?? { label: t ?? '—', hex: '#64748b', badge: 'bg-slate-500/15 text-slate-300 border-slate-500/30' }
}
export const typeHex = (t) => typeMeta(t).hex

const STATUS = {
  active: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  inactive: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  damaged: 'bg-red-500/15 text-red-300 border-red-500/30',
  planned: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
}
export const statusBadge = (s) => STATUS[s] ?? 'bg-slate-500/15 text-slate-300 border-slate-500/30'

export const READING_KINDS = [
  { key: 'reservoir', label: 'Reservoir levels', unit: 'ft', metricField: 'reservoir_elevation' },
  { key: 'generation', label: 'Generation', unit: 'MWh' },
  { key: 'reliability', label: 'Reliability', unit: '' },
]

const SEVERITY = {
  high: 'text-red-300', critical: 'text-red-400', medium: 'text-amber-300', low: 'text-slate-400',
}
export const severityTone = (s) => SEVERITY[s] ?? 'text-slate-400'
