import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useAlertsPaged, useAlertFacets, useAlertGaps, useHealth } from '@/lib/hooks'
import {
  alertModuleMeta, alertSeverityMeta, gapBadge, tierBadge, fmtDate,
  isAlertCritical, CRITICAL_SEVERITY,
} from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import PageHeader from '@/components/common/PageHeader'
import PanelState from '@/components/common/PanelState'
import { cn } from '@/lib/utils'
import { downloadCSV } from '@/lib/csv'
import { AlertTriangle, Download, FilterX, ShieldAlert } from 'lucide-react'

const DEFAULTS = { module: 'all', status: 'all', review: 'all', tier: 'all', critical: false, q: '' }

// Filters live in the URL so a triage view ("active CONTAMINATION, T1 only") is
// shareable and survives a reload — same contract as the assets table.
function useAlertFilters() {
  const [params, setParams] = useSearchParams()
  const filters = {
    module: params.get('module') || 'all',
    status: params.get('status') || 'all',
    review: params.get('review') || 'all',
    tier: params.get('tier') || 'all',
    critical: params.get('critical') === '1',
    q: params.get('q') || '',
  }
  const setFilters = (patch) => setParams((prev) => {
    const merged = { ...filters, ...patch }
    const next = new URLSearchParams(prev)
    for (const key of ['module', 'status', 'review', 'tier']) {
      merged[key] !== 'all' ? next.set(key, merged[key]) : next.delete(key)
    }
    merged.critical ? next.set('critical', '1') : next.delete('critical')
    merged.q ? next.set('q', merged.q) : next.delete('q')
    return next
  }, { replace: true })
  return [filters, setFilters]
}

// Facet options come from the backend's counts, so a newly activated alert module
// becomes filterable without touching this file.
function FacetSelect({ value, onChange, counts, allLabel, labelOf = (k) => k }) {
  const options = Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1])
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-7 flex-1 border-slate-800 bg-slate-950 text-xs" aria-label={allLabel}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all" className="text-xs">{allLabel}</SelectItem>
        {options.map(([key, count]) => (
          <SelectItem key={key} value={key} className="text-xs">
            {labelOf(key)} · {count}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function AlertRow({ alert }) {
  const mod = alertModuleMeta(alert.module_id)
  const sev = alertSeverityMeta(alert.severity)
  const critical = isAlertCritical(alert)

  return (
    <Link
      to={`/alerts/${encodeURIComponent(alert.alert_id)}`}
      className={cn(
        'flex items-start gap-3 border-b border-slate-800/70 px-4 py-2.5 transition-colors',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-sky-500/50',
        critical ? 'bg-red-950/20 hover:bg-red-950/30' : 'hover:bg-slate-800/40',
      )}
    >
      <span
        className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
        style={{ background: sev.dot }}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline" className={cn('text-[10px]', mod.badge)}>{mod.label}</Badge>
          <span className={cn('text-[10px] font-medium uppercase tracking-wide', sev.tone)}>
            {sev.label}
          </span>
          {critical && (
            <Badge variant="outline" className="border-red-500/40 bg-red-500/15 text-[10px] text-red-300">
              critical
            </Badge>
          )}
          {alert.evidence_tier && (
            <Badge variant="outline" className={cn('text-[10px]', tierBadge(alert.evidence_tier))}>
              {alert.evidence_tier}
            </Badge>
          )}
          {alert.gap_status && alert.gap_status !== 'none' && (
            <Badge variant="outline" className={cn('text-[10px]', gapBadge(alert.gap_status))}>
              gap: {alert.gap_status}
            </Badge>
          )}
        </div>
        <p className="mt-1 truncate text-xs font-medium text-slate-200">
          {alert.source_title || alert.alert_id}
        </p>
        <p className="mt-0.5 truncate text-[11px] text-slate-500">
          {(alert.municipalities ?? []).join(', ') || 'municipio unavailable'}
          {alert.asset_name ? ` · ${alert.asset_name}` : ''}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <div className="font-mono text-[10px] text-slate-500">{fmtDate(alert.start_at)}</div>
        <div className="mt-1 text-[10px] capitalize text-slate-600">{alert.status}</div>
      </div>
    </Link>
  )
}

const PAGE = 500

export default function AlertsPage() {
  const [filters, setFilters] = useAlertFilters()
  const { data: facets } = useAlertFacets()
  const { data: gaps = [] } = useAlertGaps()
  const { isError: healthError } = useHealth()
  const scrollRef = useRef(null)
  // How many rows to request. Narrowing the facets is not always enough to get under
  // one page — CONTAMINATION alone is ~3200 — so "load more" raises the ceiling and
  // the virtualized list absorbs the extra rows. Reset whenever the filters change.
  const [limit, setLimit] = useState(PAGE)

  // Server-side filtering keeps the request bounded — the corpus carries the full
  // SDWIS-derived contamination history, far more than a page should transfer.
  const query = useMemo(() => ({
    module_id: filters.module === 'all' ? undefined : filters.module,
    status: filters.status === 'all' ? undefined : filters.status,
    review_status: filters.review === 'all' ? undefined : filters.review,
    tier: filters.tier === 'all' ? undefined : filters.tier,
    critical_only: filters.critical ? true : undefined,
    q: filters.q || undefined,
  }), [filters])

  // Key the reset on the filter *values*, not on `query`'s identity: `filters` is
  // rebuilt from useSearchParams on every render, so `query` is a new object each
  // time and an identity-keyed effect would reset the limit on every render —
  // silently undoing "load more" the moment it was clicked.
  const queryKey = JSON.stringify(query)
  useEffect(() => { setLimit(PAGE) }, [queryKey])

  const { data, isLoading } = useAlertsPaged({ ...query, limit })
  const items = data?.items ?? []
  const total = data?.total ?? 0

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 74,
    overscan: 10,
  })
  const vItems = virtualizer.getVirtualItems()
  const padTop = vItems.length ? vItems[0].start : 0
  const padBottom = vItems.length ? virtualizer.getTotalSize() - vItems[vItems.length - 1].end : 0

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Operational Alerts"
        subtitle={
          facets
            ? `${facets.total} alert(s) · ${facets.active} active · ${facets.critical} critical (severity ≥ ${CRITICAL_SEVERITY}) · ${facets.mapped} mapped`
            : 'Data-driven AlertEvents promoted from ingested signals'
        }
      >
        <Button
          size="sm"
          variant="outline"
          onClick={() => downloadCSV('alerts.csv', items, [
            'alert_id', 'module_id', 'severity', 'status', 'review_status',
            'evidence_tier', 'start_at', 'source_title', 'source_ref',
          ])}
          className="h-8 border-slate-800 bg-slate-950 px-2 text-xs text-slate-400 hover:text-slate-100"
          title="Export the current page as CSV"
        >
          <Download className="mr-1 h-3.5 w-3.5" /> CSV
        </Button>
      </PageHeader>

      <div className="shrink-0 space-y-2 border-b border-slate-800 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Input
            aria-label="Search alerts"
            value={filters.q}
            onChange={(e) => setFilters({ q: e.target.value })}
            placeholder="Search alert title, asset, or id…"
            className="h-8 flex-1 border-slate-800 bg-slate-950 text-xs"
          />
          <Button
            size="sm"
            variant="outline"
            aria-pressed={filters.critical}
            onClick={() => setFilters({ critical: !filters.critical })}
            title={`Severity ≥ ${CRITICAL_SEVERITY} and still actionable`}
            className={cn('h-8 border-slate-800 px-2 text-xs',
              filters.critical ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'bg-slate-950 text-slate-400')}
          >
            <ShieldAlert className="mr-1 h-3.5 w-3.5" /> Critical
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setFilters(DEFAULTS)}
            aria-label="Clear alert filters"
            title="Clear filters"
            className="h-8 border-slate-800 bg-slate-950 px-2 text-xs text-slate-400 hover:text-slate-100"
          >
            <FilterX className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <FacetSelect
            value={filters.module}
            onChange={(v) => setFilters({ module: v })}
            counts={facets?.module_id}
            allLabel="All modules"
            labelOf={(k) => alertModuleMeta(k).label}
          />
          <FacetSelect
            value={filters.status}
            onChange={(v) => setFilters({ status: v })}
            counts={facets?.status}
            allLabel="Any status"
          />
          <FacetSelect
            value={filters.review}
            onChange={(v) => setFilters({ review: v })}
            counts={facets?.review_status}
            allLabel="Any review state"
          />
          <FacetSelect
            value={filters.tier}
            onChange={(v) => setFilters({ tier: v })}
            counts={facets?.evidence_tier}
            allLabel="Any evidence tier"
          />
        </div>
      </div>

      {gaps.length > 0 && (
        <div className="flex shrink-0 items-center gap-2 border-b border-amber-900/40 bg-amber-950/20 px-4 py-1.5 text-[11px] text-amber-300/90">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            {gaps.length} logged coverage gap(s) in the alert system —{' '}
            {gaps.map((g) => g.gap_id || g.id).filter(Boolean).join(', ')}
          </span>
        </div>
      )}

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
        <PanelState
          isLoading={isLoading}
          isError={healthError}
          isEmpty={items.length === 0}
          rows={8}
          skeletonClass="h-16"
          emptyText="No alerts match the active filters."
        >
          <div>
            {padTop > 0 && <div style={{ height: padTop }} aria-hidden="true" />}
            {vItems.map((vi) => (
              <div key={items[vi.index].alert_id} data-index={vi.index} ref={virtualizer.measureElement}>
                <AlertRow alert={items[vi.index]} />
              </div>
            ))}
            {padBottom > 0 && <div style={{ height: padBottom }} aria-hidden="true" />}
          </div>
        </PanelState>
      </div>

      {total > items.length && (
        <div
          // The AI launcher is fixed at bottom-right (z-40), so the control sits next
          // to the count rather than pinned right, where the launcher would cover it.
          className="flex shrink-0 items-center gap-3 border-t border-slate-800 py-2 pl-4 pr-44 text-[11px] text-slate-500"
        >
          <span>Showing the {items.length.toLocaleString()} most recent of {total.toLocaleString()} matching alert(s).</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setLimit((n) => n + PAGE)}
            disabled={isLoading}
            className="h-7 shrink-0 border-slate-800 bg-slate-950 px-2 text-[11px] text-slate-300 hover:text-slate-100"
          >
            Load {Math.min(PAGE, total - items.length).toLocaleString()} more
          </Button>
        </div>
      )}
    </div>
  )
}
