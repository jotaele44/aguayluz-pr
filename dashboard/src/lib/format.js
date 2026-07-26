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

// Monitoring series. Every kind here is backed by a producer script that
// scripts/refresh.py runs (see server/backend/main.py READINGS_FILES), so an empty
// chart means "not ingested yet", never "no such feed". All three share one record
// shape (site_no / metric / value / observed_date) and render as a time series.
export const READING_KINDS = [
  { key: 'reservoir', label: 'Reservoir levels', unit: 'ft', metricField: 'reservoir_elevation' },
  { key: 'groundwater', label: 'Groundwater levels', unit: 'ft', metricField: 'groundwater_level' },
  { key: 'coastal', label: 'Coastal water levels', unit: 'ft', metricField: 'coastal_water_level' },
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

// ── Operational alert layer (docs/ALERT_SYSTEM.md) ───────────────────────────

// Sector modules from config/alert_modules.yaml. Labels and tones only — the
// module list the UI *filters* on comes from GET /alerts/facets, so a newly
// activated module needs no frontend change to become selectable.
const ALERT_MODULE = {
  CONTAMINATION: { label: 'Contamination', badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  HYDRO_OPS: { label: 'Hydro ops', badge: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  POWER_OPS: { label: 'Power ops', badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  WEATHER_HAZARD: { label: 'Weather hazard', badge: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30' },
  SEISMIC_GEO: { label: 'Seismic', badge: 'bg-orange-500/15 text-orange-300 border-orange-500/30' },
  DAM_SAFETY: { label: 'Dam safety', badge: 'bg-red-500/15 text-red-300 border-red-500/30' },
  PUBLIC_NOTICE: { label: 'Public notice', badge: 'bg-slate-500/15 text-slate-300 border-slate-500/30' },
  TRANSPORT_ACCESS: { label: 'Transport', badge: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
  TELECOM_SCADA: { label: 'Telecom/SCADA', badge: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30' },
  INDUSTRIAL: { label: 'Industrial', badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
}
export function alertModuleMeta(id) {
  return ALERT_MODULE[id] ?? {
    label: id ?? 'Unclassified',
    badge: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  }
}

// The workbook's 0–5 operational severity floor. 4 is the life-safety threshold the
// exporter uses for `is_critical`; keep this in step with CRITICAL_SEVERITY in
// server/backend/main.py and aguayluz.alert_promotion.
export const CRITICAL_SEVERITY = 4
const ALERT_SEVERITY = {
  0: { label: 'Informational', tone: 'text-slate-400', dot: '#64748b' },
  1: { label: 'Low', tone: 'text-slate-300', dot: '#94a3b8' },
  2: { label: 'Moderate', tone: 'text-amber-300', dot: '#f59e0b' },
  3: { label: 'Elevated', tone: 'text-orange-300', dot: '#fb923c' },
  4: { label: 'Severe', tone: 'text-red-300', dot: '#ef4444' },
  5: { label: 'Extreme', tone: 'text-red-400', dot: '#dc2626' },
}
export function alertSeverityMeta(severity) {
  return ALERT_SEVERITY[severity] ?? { label: '—', tone: 'text-slate-400', dot: '#64748b' }
}

// Lifecycle states that make an alert current. Mirrors ACTIONABLE_ALERT_STATUS in
// the backend, so "active" means the same thing in the list, the map, and /health.
export const ACTIONABLE_ALERT_STATUS = ['active', 'validated']
export const isAlertCritical = (a) =>
  Number.isInteger(a?.severity) &&
  a.severity >= CRITICAL_SEVERITY &&
  ACTIONABLE_ALERT_STATUS.includes(a?.status)

// gap_status from the workbook: how complete the evidence behind an alert is.
const GAP_STATUS = {
  none: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  minor: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  major: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
  blocking: 'bg-red-500/15 text-red-300 border-red-500/30',
}
export const gapBadge = (g) => GAP_STATUS[g] ?? GAP_STATUS.none

// Canonical Recharts tooltip style — one source of truth for every chart.
export const CHART_TOOLTIP_STYLE = {
  background: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 6,
  fontSize: 11,
  color: '#cbd5e1',
}
