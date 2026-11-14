import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Calendar, Database, Droplets, Waves } from 'lucide-react'

import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'
import Panel from '@/components/common/Panel'
import PanelState from '@/components/common/PanelState'
import { Button } from '@/components/ui/button'
import { fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useWaterUseEstimates } from '@/lib/water-use-hooks'

const FALLBACK_SCOPE = 'U.S. Geological Survey estimates of freshwater withdrawals in Puerto Rico, published every five years. They are not measurements of current production.'

const SURFACE_BAR = 'bg-sky-500/70'
const GROUND_BAR = 'bg-amber-500/70'

const mgd = (value) => (value == null ? '—' : Number(value).toFixed(2))
const pct = (value) => (value == null ? '—' : `${Number(value).toFixed(1)}%`)

function Badge({ className, children }) {
  return (
    <span className={cn('inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium', className)}>
      {children}
    </span>
  )
}

function TierBadge({ figure }) {
  const transcribed = figure.extraction_method === 'manual_transcription'
  return (
    <Badge className={transcribed ? 'border-amber-500/40 bg-amber-500/10 text-amber-300' : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'}>
      {figure.evidence_tier} · {transcribed ? 'transcribed from PDF' : 'data-release table'}
    </Badge>
  )
}

// Surface and groundwater as shares of their sum. The numbers are in the table beside it and
// in the bar's text alternative; colour only reinforces them.
function SplitBar({ year, figure }) {
  const { surface_pct: surface, groundwater_pct: ground } = figure
  if (surface == null || ground == null) {
    return <span className="text-slate-500">split by source not published</span>
  }
  return (
    <div
      role="img"
      aria-label={`${year} public supply: ${pct(surface)} surface water, ${pct(ground)} groundwater`}
      data-testid={`split-bar-${year}`}
      className="flex h-4 w-56 min-w-[14rem] overflow-hidden rounded bg-slate-900"
    >
      <div className={SURFACE_BAR} style={{ width: `${surface}%` }} />
      <div className={GROUND_BAR} style={{ width: `${ground}%` }} />
    </div>
  )
}

function Legend() {
  return (
    <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400" aria-label="Source legend">
      <li className="flex items-center gap-1.5"><span className={cn('inline-block h-2.5 w-4 rounded-sm', SURFACE_BAR)} aria-hidden="true" />Surface water (rivers and reservoirs)</li>
      <li className="flex items-center gap-1.5"><span className={cn('inline-block h-2.5 w-4 rounded-sm', GROUND_BAR)} aria-hidden="true" />Groundwater (wells)</li>
    </ul>
  )
}

function PublicSupplyTable({ years }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-left text-xs" aria-label="Public-supply withdrawals by source">
        <thead className="text-[11px] uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="py-2 pr-3 font-medium">Year</th>
            <th className="py-2 pr-3 text-right font-medium">Surface water</th>
            <th className="py-2 pr-3 text-right font-medium">Groundwater</th>
            <th className="py-2 pr-3 text-right font-medium">Total</th>
            <th className="py-2 pr-3 font-medium">Share by source</th>
            <th className="py-2 pr-3 font-medium">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => {
            const slot = year.categories.public_supply
            const figure = slot?.published
            if (!figure) return null
            return (
              <tr key={year.year} className="border-b border-slate-900 align-top" data-testid={`water-use-year-${year.year}`}>
                <th scope="row" className="py-2 pr-3 text-sm font-semibold text-slate-100">{year.year}</th>
                <td className="py-2 pr-3 text-right text-slate-200">
                  {mgd(figure.surface_water_mgd)}
                  <div className="text-[11px] text-slate-500">{pct(figure.surface_pct)}</div>
                </td>
                <td className="py-2 pr-3 text-right text-slate-200">
                  {mgd(figure.groundwater_mgd)}
                  <div className="text-[11px] text-slate-500">{pct(figure.groundwater_pct)}</div>
                </td>
                <td className="py-2 pr-3 text-right font-semibold text-slate-100">{mgd(figure.total_mgd)}</td>
                <td className="py-2 pr-3"><SplitBar year={year.year} figure={figure} /></td>
                <td className="py-2 pr-3">
                  <TierBadge figure={figure} />
                  {slot.restated && (
                    <div className="mt-1 text-[11px] text-amber-200/90">
                      Restated as {mgd(slot.restated.total_mgd)} in a later USGS release
                    </div>
                  )}
                  {figure.notes.map((note) => (
                    <div key={note} className="mt-1 max-w-xs text-[11px] text-slate-500">{note}</div>
                  ))}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Restatements({ items, categories }) {
  if (!items.length) return null
  const label = (id) => categories.find((c) => c.id === id)?.label ?? id
  return (
    <div role="note" aria-label="Restated figures" className="mt-4 rounded border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100/90">
      <div className="font-medium">USGS published two different values for the same year</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {items.map((item) => (
          <li key={`${item.year}-${item.category}`}>
            {item.year} {label(item.category).toLowerCase()}: {mgd(item.published_total_mgd)} in the original report,{' '}
            {mgd(item.restated_total_mgd)} in the later release. The source gives no reason, so none is offered here.
          </li>
        ))}
      </ul>
    </div>
  )
}

function CategoryTable({ year, categories }) {
  const rows = categories
    .map((c) => ({ ...c, figure: year.categories[c.id]?.published }))
    .filter((c) => c.figure)
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-xs" aria-label={`Freshwater withdrawals by category, ${year.year}`}>
        <thead className="text-[11px] uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-800">
            <th className="py-2 pr-3 font-medium">Category</th>
            <th className="py-2 pr-3 text-right font-medium">Surface water</th>
            <th className="py-2 pr-3 text-right font-medium">Groundwater</th>
            <th className="py-2 pr-3 text-right font-medium">Total</th>
            <th className="py-2 pr-3 text-right font-medium">Groundwater share</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ id, label, figure }) => (
            <tr key={id} className={cn('border-b border-slate-900', id === 'total_freshwater' && 'font-semibold text-slate-100')}>
              <th scope="row" className="py-1.5 pr-3 font-medium text-slate-200">{label}</th>
              <td className="py-1.5 pr-3 text-right text-slate-300">{mgd(figure.surface_water_mgd)}</td>
              <td className="py-1.5 pr-3 text-right text-slate-300">{mgd(figure.groundwater_mgd)}</td>
              <td className="py-1.5 pr-3 text-right text-slate-200">{mgd(figure.total_mgd)}</td>
              <td className="py-1.5 pr-3 text-right text-slate-300">{pct(figure.groundwater_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MunicipioTable({ tables }) {
  const available = Object.keys(tables).sort().reverse()
  const [selected, setSelected] = useState(null)
  const year = selected && available.includes(selected) ? selected : available[0]
  if (!year) return null
  // Largest groundwater withdrawals first: that is the question this page is opened for.
  const rows = [...tables[year]].sort((a, b) => (b.groundwater_mgd ?? 0) - (a.groundwater_mgd ?? 0))
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label="Year">
        {available.map((y) => (
          <Button
            key={y}
            size="sm"
            variant="outline"
            aria-pressed={y === year}
            onClick={() => setSelected(y)}
            className={cn('h-7 border-slate-700 bg-slate-950 text-xs', y === year ? 'border-sky-500/60 text-sky-200' : 'text-slate-400')}
          >
            {y}
          </Button>
        ))}
        <span className="text-[11px] text-slate-500">Sorted by groundwater withdrawal, largest first. The 2010 report is not broken out by municipality here.</span>
      </div>
      <div className="max-h-[28rem] overflow-auto">
        <table className="w-full min-w-[520px] text-left text-xs" aria-label={`Public-supply withdrawals by municipality, ${year}`}>
          <thead className="sticky top-0 bg-slate-900 text-[11px] uppercase tracking-wide text-slate-500">
            <tr className="border-b border-slate-800">
              <th className="py-2 pr-3 font-medium">Municipality of intake</th>
              <th className="py-2 pr-3 text-right font-medium">Surface water</th>
              <th className="py-2 pr-3 text-right font-medium">Groundwater</th>
              <th className="py-2 pr-3 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.municipality} className="border-b border-slate-900">
                <th scope="row" className="py-1.5 pr-3 font-medium text-slate-200">{row.municipality}</th>
                <td className="py-1.5 pr-3 text-right text-slate-300">{mgd(row.surface_water_mgd)}</td>
                <td className="py-1.5 pr-3 text-right text-slate-300">{mgd(row.groundwater_mgd)}</td>
                <td className="py-1.5 pr-3 text-right text-slate-200">{mgd(row.total_mgd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function SourcePanel({ source }) {
  const failed = source.last_status === 'FAIL'
  return (
    <Panel>
      <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">Sources and provenance</h2>
      <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4" data-testid="water-use-source">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="text-xs text-slate-400">
            Last read: {source.last_success_utc ? fmtDate(source.last_success_utc) : 'never'}. Every file is pinned by
            SHA-256; a file whose bytes change stops the read until a person has looked at it.
          </div>
          <Badge className={failed ? 'border-red-500/40 bg-red-500/10 text-red-300' : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'}>
            {source.last_status ?? 'NEVER'}
          </Badge>
        </div>
        {failed && (
          <div role="alert" className="mt-3 rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-200">
            Latest attempt failed: {source.last_error}. The figures shown are the last ones verified.
          </div>
        )}
        <ul className="mt-3 space-y-2 text-xs">
          {source.sources.map((s) => (
            <li key={s.source_key} className="border-t border-slate-800 pt-2">
              <div className="text-slate-200">{s.title}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                <span>Data year {s.year}</span>
                <span>{s.evidence_tier} · {s.extraction_method === 'manual_transcription' ? 'transcribed from PDF' : 'read from xlsx'}</span>
                {String(s.url || '').startsWith('https://') && (
                  <a className="text-sky-300 hover:underline" href={s.url} target="_blank" rel="noopener noreferrer">doi:{s.doi}</a>
                )}
              </div>
              <div className="mt-0.5 break-all font-mono text-[11px] text-slate-500">SHA-256 {s.sha256}</div>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  )
}

export default function WaterUsePage() {
  const query = useWaterUseEstimates()
  const data = query.data
  const years = data?.years ?? []
  const categories = data?.categories ?? []
  const latest = years.length ? years[years.length - 1] : null
  const latestSupply = latest?.categories.public_supply?.published
  const detailed = [...years].reverse().find((y) => Object.keys(y.categories).length > 3)
  const municipios = data?.municipios?.public_supply ?? {}

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Water Use"
        subtitle="USGS estimates of public-supply withdrawals in Puerto Rico by source: surface water and groundwater"
      />
      <div className="min-h-0 flex-1 space-y-5 overflow-auto p-6">
        <ErrorBoundary label="Water-use estimates">
          <div role="note" aria-label="Water use scope" className="flex items-start gap-3 rounded-lg border border-sky-500/30 bg-sky-500/10 p-4">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" aria-hidden="true" />
            <div className="space-y-1 text-sm text-sky-100/90">
              <p>{data?.scope?.statement ?? FALLBACK_SCOPE}</p>
              <p className="text-xs text-sky-200/80">
                For the current state of the south-coast aquifer, see{' '}
                <Link className="underline hover:text-sky-100" to="/aquifer-bands">Aquifer Bands</Link>.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: 'Latest year', value: latest?.year ?? '—', icon: Calendar },
              { label: 'Public supply (Mgal/d)', value: latestSupply ? mgd(latestSupply.total_mgd) : '—', icon: Droplets },
              { label: 'From surface water', value: latestSupply ? pct(latestSupply.surface_pct) : '—', icon: Waves },
              { label: 'From groundwater', value: latestSupply ? pct(latestSupply.groundwater_pct) : '—', icon: Database },
            ].map(({ label, value, icon: Icon }) => (
              <div key={label} className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
                <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500"><Icon className="h-4 w-4" aria-hidden="true" />{label}</div>
                <div className="mt-2 text-2xl font-semibold text-slate-100">{value}</div>
              </div>
            ))}
          </div>

          <Panel>
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">Public supply by source</h2>
            <p className="mb-3 max-w-3xl text-xs text-slate-500">
              Million gallons per day withdrawn by PRASA and non-PRASA community water systems. Shares are of surface water
              plus groundwater.
            </p>
            <PanelState
              isLoading={query.isLoading}
              isError={query.isError}
              errorText={(
                <div className="space-y-2">
                  <div>Water-use estimates unavailable: {String(query.error?.message ?? query.error)}</div>
                  <Button size="sm" variant="outline" onClick={() => query.refetch()} className="h-7 border-slate-700 bg-slate-950 text-xs text-slate-300">
                    Retry water use
                  </Button>
                </div>
              )}
              isEmpty={!years.length}
              emptyText="No water-use estimates loaded yet. They are read from the USGS releases by scripts/ingest_usgs_water_use.py."
            >
              <Legend />
              <PublicSupplyTable years={years} />
              <Restatements items={data?.restatements ?? []} categories={categories} />
            </PanelState>
          </Panel>

          {detailed && (
            <Panel>
              <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">All freshwater categories, {detailed.year}</h2>
              <p className="mb-3 max-w-3xl text-xs text-slate-500">
                Public supply is one category. The last row is every category together; its split by source is not the
                public-supply split, and the two are often confused.
              </p>
              <CategoryTable year={detailed} categories={categories} />
            </Panel>
          )}

          {Object.keys(municipios).length > 0 && (
            <Panel>
              <h2 className="mb-4 text-xs font-semibold uppercase tracking-widest text-slate-400">Public supply by municipality</h2>
              <p className="mb-3 max-w-3xl text-xs text-slate-500">
                Withdrawals are counted where the intake is, not where the water is used: a municipality with no intake
                shows zero and is still served.
              </p>
              <MunicipioTable tables={municipios} />
            </Panel>
          )}

          {data?.source && (years.length > 0 || data.source.last_status) && <SourcePanel source={data.source} />}
        </ErrorBoundary>
      </div>
    </div>
  )
}
