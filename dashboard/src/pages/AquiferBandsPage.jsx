import { AlertTriangle, Database, Droplets, Gauge, ShieldAlert } from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import Panel from '@/components/common/Panel'
import PanelState from '@/components/common/PanelState'
import { Button } from '@/components/ui/button'
import { useAquiferBands } from '@/lib/aquifer-hooks'
import { fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'

// FRESH: last successful read of the source page is within the max age. STALE: older.
// FAILED: the latest attempt failed (the last success is still shown). NEVER: no receipt yet.
const FRESHNESS_STYLE = {
  FRESH: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  STALE: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  FAILED: 'border-red-500/40 bg-red-500/10 text-red-300',
  NEVER: 'border-slate-600 bg-slate-800/60 text-slate-300',
}

// The class is always written out as text; colour only reinforces it.
const CLASS_STYLE = {
  above_optimum: { badge: 'border-emerald-600/40 bg-emerald-600/10 text-emerald-300', bar: 'bg-emerald-700/50' },
  optimum: { badge: 'border-sky-500/40 bg-sky-500/10 text-sky-200', bar: 'bg-sky-500/60' },
  observation: { badge: 'border-yellow-500/50 bg-yellow-500/15 text-yellow-200', bar: 'bg-yellow-400/60' },
  operational_adjustment: { badge: 'border-orange-500/50 bg-orange-500/15 text-orange-200', bar: 'bg-orange-500/60' },
  critical: { badge: 'border-red-500/50 bg-red-500/15 text-red-200', bar: 'bg-red-600/70' },
}

const FALLBACK_SCOPE = 'These condition bands are attributed to PRDNER by a USGS page and are applied to provisional readings. A class is an observed condition, not an alert.'

const feet = (value) => (value == null ? '—' : `${Number(value).toFixed(2)} ft`)

const marginText = (margin) => {
  if (margin == null) return '—'
  return margin >= 0
    ? `${feet(margin)} before Critical`
    : `${feet(Math.abs(margin))} past Critical onset`
}

const ageText = (seconds) => {
  if (seconds == null) return '—'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} d ago`
}

const labelFor = (classes, id) => classes.find((c) => c.id === id)?.label ?? String(id).replaceAll('_', ' ')

function Badge({ className, children }) {
  return (
    <span className={cn('inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium', className)}>
      {children}
    </span>
  )
}

// One stacked bar per well, scaled to that well's own chart axis. The depth marker is clamped
// to the axis end: a depth beyond it is still Critical, and the text columns carry the number.
function BandBar({ item, classes }) {
  const axis = item.axis_max_ft
  const depth = item.reading?.value_ft
  const markerLeft = depth == null ? null : Math.max(0, Math.min(99, (depth / axis) * 100))
  const description = `${item.name}. Bands, in feet below land surface: ${item.bands
    .map((b) => `${labelFor(classes, b.class)} ${b.shallow_ft} to ${b.deep_ft}`)
    .join('; ')}. ${depth == null ? 'No current reading.' : `Latest depth ${depth} feet.`}`
  return (
    <div
      role="img"
      aria-label={description}
      data-testid={`band-bar-${item.site_no}`}
      className="relative h-4 w-56 min-w-[14rem] overflow-hidden rounded bg-slate-900"
    >
      <div className="flex h-full">
        {item.bands.map((b) => (
          <div
            key={b.class}
            className={CLASS_STYLE[b.class]?.bar ?? 'bg-slate-700'}
            style={{ width: `${((b.deep_ft - b.shallow_ft) / axis) * 100}%` }}
          />
        ))}
      </div>
      {markerLeft != null && (
        <div className="absolute inset-y-0 w-0.5 bg-slate-50" style={{ left: `${markerLeft}%` }} />
      )}
    </div>
  )
}

function BandEdges({ item, classes }) {
  return (
    <details className="mt-1 text-[11px] text-slate-500">
      <summary className="cursor-pointer select-none text-slate-400">Band edges</summary>
      <ul className="mt-1 space-y-0.5">
        {item.bands.map((b) => (
          <li key={b.class}>
            {labelFor(classes, b.class)}: {b.shallow_ft} – {b.deep_ft} ft
          </li>
        ))}
      </ul>
    </details>
  )
}

function WellTable({ items, classes }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] text-left text-xs" aria-label="Aquifer observation wells">
        <thead className="text-[11px] uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="py-2 pr-3 font-medium">Well</th>
            <th className="py-2 pr-3 font-medium">Depth to water</th>
            <th className="py-2 pr-3 font-medium">Condition</th>
            <th className="py-2 pr-3 font-medium">Margin</th>
            <th className="py-2 pr-3 font-medium">Bands (ft below land surface)</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const r = item.reading
            return (
              <tr key={item.site_no} className="border-b border-slate-900 align-top" data-testid={`aquifer-well-${item.site_no}`}>
                <td className="py-2 pr-3">
                  <div className="font-medium text-slate-200">{item.name}</div>
                  <div className="font-mono text-[11px] text-slate-500">{item.asset_id}</div>
                  <div className="text-[11px] text-slate-500">{item.municipality ?? 'municipio unknown'}</div>
                </td>
                <td className="py-2 pr-3 text-slate-300">
                  {r ? (
                    <>
                      <div className="text-sm font-semibold text-slate-100">{feet(r.value_ft)}</div>
                      <div className={cn('text-[11px]', r.stale ? 'text-amber-300' : 'text-slate-500')}>
                        {r.observed_date}{r.stale ? ' · stale' : ''}
                      </div>
                      <Badge className={r.provisional ? 'mt-1 border-amber-500/40 bg-amber-500/10 text-amber-300' : 'mt-1 border-slate-600 bg-slate-800/60 text-slate-300'}>
                        {r.provisional ? 'Provisional' : 'Approved'}
                      </Badge>
                    </>
                  ) : (
                    <span className="text-slate-500">no reading</span>
                  )}
                </td>
                <td className="py-2 pr-3">
                  {item.class ? (
                    <Badge className={cn('whitespace-normal', CLASS_STYLE[item.class]?.badge)}>{item.class_label}</Badge>
                  ) : (
                    <span className="text-slate-500">No current reading, so no condition is claimed</span>
                  )}
                </td>
                <td className={cn('py-2 pr-3', item.margin_to_critical_ft != null && item.margin_to_critical_ft < 0 ? 'font-medium text-red-300' : 'text-slate-300')}>
                  {marginText(item.margin_to_critical_ft)}
                  <div className="text-[11px] font-normal text-slate-500">Critical from {feet(item.critical_onset_ft)}</div>
                </td>
                <td className="py-2 pr-3">
                  <BandBar item={item} classes={classes} />
                  <BandEdges item={item} classes={classes} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Legend({ classes }) {
  return (
    <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400" aria-label="Band legend">
      {classes.map((c) => (
        <li key={c.id} className="flex items-center gap-1.5">
          <span className={cn('inline-block h-2.5 w-4 rounded-sm', CLASS_STYLE[c.id]?.bar)} aria-hidden="true" />
          {c.label}
        </li>
      ))}
    </ul>
  )
}

function SourcePanel({ data }) {
  const source = data.source
  const receipt = source?.receipt
  const success = receipt?.last_success
  const state = source?.freshness?.state ?? 'NEVER'
  const arithmetic = success?.arithmetic
  const discrepancies = data.items.flatMap((i) => i.ladder_discrepancies.map((d) => `${i.name}: ${d}`))
  return (
    <Panel>
      <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">Source and provenance</h2>
      <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4" data-testid="aquifer-source">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-100">USGS: groundwater levels at selected observation wells, south coast</div>
            <div className="text-xs text-slate-500">{data.scope?.authority_claim}</div>
          </div>
          <Badge className={FRESHNESS_STYLE[state]}>{state}</Badge>
        </div>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
          <div><dt className="inline text-slate-500">Last read: </dt><dd className="inline text-slate-300">{receipt?.last_success_utc ? `${fmtDate(receipt.last_success_utc)} (${ageText(source.freshness?.age_seconds)})` : 'never'}</dd></div>
          <div><dt className="inline text-slate-500">Last attempt: </dt><dd className="inline text-slate-300">{receipt?.last_attempt_utc ? `${fmtDate(receipt.last_attempt_utc)} — ${receipt.last_status}` : 'never'}</dd></div>
          <div><dt className="inline text-slate-500">Wells accounted: </dt><dd className="inline text-slate-300">{arithmetic ? `${arithmetic.source} source = ${arithmetic.retained} retained + ${arithmetic.excluded} excluded + ${arithmetic.unresolved} unresolved (${arithmetic.state})` : '—'}</dd></div>
          <div><dt className="inline text-slate-500">Evidence tier: </dt><dd className="inline text-slate-300">{data.scope?.evidence_tier ?? '—'} · effective date {data.scope?.effective_date ?? 'not published by the source'}</dd></div>
          <div className="sm:col-span-2"><dt className="inline text-slate-500">Page: </dt><dd className="inline break-all font-mono text-[11px] text-slate-400">
            {String(source?.url || '').startsWith('https://')
              ? <a className="text-sky-300 hover:underline" href={source.url} target="_blank" rel="noopener noreferrer">{source.url}</a>
              : '—'}
          </dd></div>
          <div className="sm:col-span-2"><dt className="inline text-slate-500">Fetched bytes SHA-256: </dt><dd className="inline break-all font-mono text-[11px] text-slate-400">{success?.byte_sha256 ?? '—'}</dd></div>
        </dl>
        {receipt?.last_status === 'FAIL' && (
          <div role="alert" className="mt-3 rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-200">
            Latest attempt failed: {receipt.last_error}. The bands shown are the last ones verified.
          </div>
        )}
        {state === 'STALE' && (
          <div role="alert" className="mt-3 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-200">
            The source page has not been read successfully within {Math.round((source.freshness?.max_age_seconds ?? 0) / 86400)} days. The bands may have changed.
          </div>
        )}
        <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
          The hash identifies the exact bytes fetched. It differs on every fetch of identical content, because the page&apos;s CDN
          injects a per-request script, so it is evidence of what was read rather than a sign that the bands changed.
          Bands are versioned by registry revision.
        </p>
        {discrepancies.length > 0 && (
          <div className="mt-3 text-[11px] text-slate-500">
            <div className="font-medium text-slate-400">Differences within the source page itself (chart ranges are used):</div>
            <ul className="mt-1 list-disc pl-5">{discrepancies.map((d) => <li key={d}>{d}</li>)}</ul>
          </div>
        )}
        <div className="mt-3 text-[11px] text-slate-500">
          <div className="font-medium text-slate-400">Reference pages named by the source (recorded; this app does not fetch or verify them):</div>
          <ul className="mt-1 space-y-0.5">
            {data.items.filter((i) => String(i.reference_url || '').startsWith('https://')).map((i) => (
              <li key={i.site_no}>
                <a className="text-sky-300 hover:underline" href={i.reference_url} target="_blank" rel="noopener noreferrer">{i.name}</a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Panel>
  )
}

export default function AquiferBandsPage() {
  const query = useAquiferBands()
  const data = query.data
  const items = data?.items ?? []
  const classes = data?.classes ?? []
  const counts = data?.counts

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Aquifer Bands"
        subtitle="South-coast observation wells against the condition bands a USGS page attributes to PRDNER"
      />
      <div className="min-h-0 flex-1 space-y-5 overflow-auto p-6">
        <ErrorBoundary label="Aquifer condition bands">
          <div role="note" aria-label="Aquifer bands scope" className="flex items-start gap-3 rounded-lg border border-sky-500/30 bg-sky-500/10 p-4">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" aria-hidden="true" />
            <div className="space-y-1 text-sm text-sky-100/90">
              <p>{data?.scope?.statement ?? FALLBACK_SCOPE}</p>
              {data?.scope?.alerting_reason && <p className="text-xs text-sky-200/80">{data.scope.alerting_reason}</p>}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: 'Wells', value: counts?.wells ?? '—', icon: Droplets },
              { label: 'With a reading', value: counts?.with_reading ?? '—', icon: Gauge },
              { label: 'In Critical', value: counts?.critical ?? '—', icon: ShieldAlert },
              { label: 'Provisional readings', value: counts?.provisional_readings ?? '—', icon: Database },
            ].map(({ label, value, icon: Icon }) => (
              <div key={label} className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
                <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500"><Icon className="h-4 w-4" aria-hidden="true" />{label}</div>
                <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
              </div>
            ))}
          </div>

          <Panel>
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">Observation wells</h2>
            <p className="mb-3 max-w-3xl text-xs text-slate-500">
              Depth to water in feet below land surface: a larger number is a deeper water table. The latest local reading of each
              well is placed against its own bands; the marker on each bar is clamped at the end of the chart axis.
            </p>
            <PanelState
              isLoading={query.isLoading}
              isError={query.isError}
              errorText={(
                <div className="space-y-2">
                  <div>Aquifer bands unavailable: {String(query.error?.message ?? query.error)}</div>
                  <Button size="sm" variant="outline" onClick={() => query.refetch()} className="h-7 border-slate-700 bg-slate-950 text-xs text-slate-300">
                    Retry aquifer bands
                  </Button>
                </div>
              )}
              isEmpty={!items.length}
              emptyText="No aquifer bands registered yet. They are read from the USGS page by the weekly refresh."
            >
              <Legend classes={classes} />
              <WellTable items={items} classes={classes} />
            </PanelState>
          </Panel>

          {/* Also when there are no wells but a receipt exists: a page that never parsed must say why. */}
          {data && (items.length > 0 || data.source?.receipt) && <SourcePanel data={data} />}
        </ErrorBoundary>
      </div>
    </div>
  )
}
