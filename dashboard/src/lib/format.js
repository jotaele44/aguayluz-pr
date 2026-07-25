// Shared display helpers (badge tones, map colors, dates). Reused by MapView
// and the side panels. Hex values feed MapLibre paint; class strings feed
// shadcn <Badge>.

import { federationTone } from '@pr-federation/react'
import { cn } from '@/lib/utils'

// Evidence tier T1 (strongest) → T4 (weakest).
const TIER = {
  T1: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  T2: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30',
  T3: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  T4: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
}
export const tierBadge = (tier) => TIER[tier] ?? TIER.T4

// Review-queue filter options — shared by the Review page and the map-rail panel.
export const SEVERITIES = ['all', 'block', 'warn', 'info']
export const TIERS = ['all', 'T1', 'T2', 'T3', 'T4']

export function fmtDate(s) {
  if (!s) return '—'
  // Accept ISO date or datetime; show YYYY-MM-DD HH:MM when time present.
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const hasTime = /\d{2}:\d{2}/.test(s)
  return hasTime ? d.toISOString().slice(0, 16).replace('T', ' ') : s.slice(0, 10)
}

// ── Domain display helpers (asset type / status / readings / severity) ──

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

// Asset status now renders on the shared federation status tokens instead of
// local Tailwind hues. Map the app's status vocabulary to canonical roles;
// federationTone() returns { className: 'fd-status', 'data-status': role } and
// the colors come from the imported @pr-federation/react/styles.css.
const STATUS_ROLE = {
  active: 'success',
  inactive: 'neutral',
  damaged: 'danger',
  planned: 'warning',
}
export const statusTone = (s, extra) => {
  const { className, ...toneAttrs } = federationTone(STATUS_ROLE[s] ?? 'neutral')
  return { className: cn(className, extra), ...toneAttrs }
}

export const READING_KINDS = [
  { key: 'reservoir', label: 'Reservoir levels', unit: 'ft', metricField: 'reservoir_elevation' },
  { key: 'generation', label: 'Generation', unit: 'MWh' },
  { key: 'reliability', label: 'Reliability', unit: '' },
]

const SEVERITY = {
  high: 'text-red-300', critical: 'text-red-400', medium: 'text-amber-300', low: 'text-slate-400',
}
export const severityTone = (s) => SEVERITY[s] ?? 'text-slate-400'

// ── Event-type tones (shared by outages panel, asset detail, live logs) ──

const EVENT_TONE = {
  outage: 'text-red-300',
  service_interruption: 'text-amber-300',
  restoration: 'text-emerald-300',
  boil_water: 'text-sky-300',
  project_update: 'text-violet-300',
}
export const eventTone = (t) => EVENT_TONE[t] ?? 'text-slate-400'

const EVENT_PILL = {
  outage: 'bg-red-950/60 text-red-300 border-red-900',
  service_interruption: 'bg-amber-950/60 text-amber-300 border-amber-900',
  restoration: 'bg-emerald-950/60 text-emerald-300 border-emerald-900',
  boil_water: 'bg-sky-950/60 text-sky-300 border-sky-900',
  project_update: 'bg-violet-950/60 text-violet-300 border-violet-900',
}
export const eventPill = (t) => EVENT_PILL[t] ?? 'bg-slate-900 border-slate-800 text-slate-400'

export const EVENT_TYPES = ['all', 'outage', 'service_interruption', 'restoration', 'boil_water', 'project_update']

// Canonical Recharts tooltip style — one source of truth for every chart.
export const CHART_TOOLTIP_STYLE = {
  background: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 6,
  fontSize: 11,
  color: '#cbd5e1',
}
