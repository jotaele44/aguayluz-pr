import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { tierBadge, typeMeta, statusTone } from '@/lib/format'
import { cn } from '@/lib/utils'
import { AlertTriangle, ChevronsUpDown, ChevronUp, ChevronDown, Download, FilterX } from 'lucide-react'
import { downloadCSV } from '@/lib/csv'

function normalized(value) {
  return `${value ?? ''}`.toLowerCase()
}

function needsReview(asset) {
  return asset.review_status === 'needs_review' || asset.status === 'needs_review' || asset.review_status === 'review'
}

const DEFAULT_FILTERS = { type: 'all', status: 'all', reviewOnly: false, q: '' }

// Filter state. With `syncUrl` (the standalone Assets page) it lives in the URL so
// a filtered view is shareable and reload-stable; otherwise (the map rail, where
// two instances would collide on one URL) it stays local. Both hooks run every
// render — `syncUrl` is fixed per mount, so the branch never skips a hook.
function useAssetFilters(syncUrl) {
  const [params, setParams] = useSearchParams()
  const [local, setLocal] = useState(DEFAULT_FILTERS)

  if (syncUrl) {
    const filters = {
      type: params.get('type') || 'all',
      status: params.get('status') || 'all',
      reviewOnly: params.get('review') === '1',
      q: params.get('q') || '',
    }
    const setFilters = (patch) => setParams((prev) => {
      const merged = { ...filters, ...patch }
      const next = new URLSearchParams(prev)
      merged.type !== 'all' ? next.set('type', merged.type) : next.delete('type')
      merged.status !== 'all' ? next.set('status', merged.status) : next.delete('status')
      merged.reviewOnly ? next.set('review', '1') : next.delete('review')
      merged.q ? next.set('q', merged.q) : next.delete('q')
      return next
    }, { replace: true })
    return [filters, setFilters]
  }
  return [local, (patch) => setLocal((s) => ({ ...s, ...patch }))]
}

function SortIcon({ col, sort }) {
  if (sort.col !== col) return <ChevronsUpDown className="inline h-3 w-3 ml-0.5 text-slate-600" />
  return sort.dir === 'asc'
    ? <ChevronUp className="inline h-3 w-3 ml-0.5 text-sky-400" />
    : <ChevronDown className="inline h-3 w-3 ml-0.5 text-sky-400" />
}

const COLS = [
  { key: 'asset_name', label: 'Asset' },
  { key: 'asset_type', label: 'Type' },
  { key: 'municipality', label: 'Municipio' },
  { key: 'status', label: 'Evidence' },
]

export default function AssetsTable({ assets = [], isLoading, selectedId, onSelect, syncUrl = false }) {
  const [{ type, status, reviewOnly, q }, setFilters] = useAssetFilters(syncUrl)
  const [sort, setSort] = useState({ col: 'asset_name', dir: 'asc' })
  const scrollRef = useRef(null)
  const searchRef = useRef(null)

  const types = useMemo(
    () => ['all', ...Array.from(new Set(assets.map((a) => a.asset_type).filter(Boolean))).sort()],
    [assets],
  )
  const statuses = useMemo(
    () => ['all', ...Array.from(new Set(assets.map((a) => a.status).filter(Boolean))).sort()],
    [assets],
  )

  const toggleSort = (col) => {
    setSort((s) => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' })
  }

  const rows = useMemo(() => {
    const filtered = assets.filter((a) => {
      const haystack = [a.asset_name, a.municipality, a.operator, a.asset_type, a.asset_subtype, a.source_ref, a.asset_id]
        .map(normalized).join(' ')
      return (
        (type === 'all' || a.asset_type === type) &&
        (status === 'all' || a.status === status) &&
        (!reviewOnly || needsReview(a)) &&
        (!q || haystack.includes(normalized(q)))
      )
    })
    return [...filtered].sort((a, b) => {
      const av = normalized(a[sort.col])
      const bv = normalized(b[sort.col])
      return sort.dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
    })
  }, [assets, type, status, reviewOnly, q, sort])

  // Window the rows so large asset corpora stay smooth; heights are measured
  // dynamically because badge wrapping makes some rows taller than others.
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 44,
    overscan: 12,
  })
  const vItems = virtualizer.getVirtualItems()
  const paddingTop = vItems.length ? vItems[0].start : 0
  const paddingBottom = vItems.length ? virtualizer.getTotalSize() - vItems[vItems.length - 1].end : 0

  // "/" focuses search; j/k move the selection (skips while typing in a field).
  useEffect(() => {
    const handler = (e) => {
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === '/') {
        e.preventDefault()
        searchRef.current?.focus()
        return
      }
      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault()
        const idx = rows.findIndex((a) => a.asset_id === selectedId)
        const next = e.key === 'j'
          ? Math.min(idx + 1, rows.length - 1)
          : Math.max(idx - 1, 0)
        if (rows[next]) {
          onSelect?.(rows[next])
          virtualizer.scrollToIndex(next, { align: 'auto' })
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [rows, selectedId, onSelect, virtualizer])

  const clear = () => setFilters(DEFAULT_FILTERS)

  if (isLoading) {
    return (
      <div className="flex flex-col h-full p-2 space-y-1">
        <Skeleton className="h-7 w-full mb-1" />
        {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="space-y-2 border-b border-slate-900 px-2 pb-2">
        <div className="flex items-center gap-2">
          <div className="w-12 shrink-0 text-xs text-slate-400">{rows.length}</div>
          <Input
            value={q}
            onChange={(e) => setFilters({ q: e.target.value })}
            ref={searchRef}
            placeholder="Search asset, municipio, operator, source… (press / to focus)"
            className="h-8 flex-1 border-slate-800 bg-slate-950 text-xs"
          />
          <Button size="sm" variant="outline" onClick={clear} aria-label="Clear filters" title="Clear filters" className="h-8 border-slate-800 bg-slate-950 px-2 text-xs text-slate-400 hover:text-slate-100">
            <FilterX className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="outline" onClick={() => downloadCSV('assets.csv', rows, ['asset_id','asset_name','asset_type','municipality','status','operator','evidence_tier'])} className="h-8 border-slate-800 bg-slate-950 px-2 text-xs text-slate-400 hover:text-slate-100" title="Export CSV">
            <Download className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <Select value={type} onValueChange={(v) => setFilters({ type: v })}>
            <SelectTrigger className="h-7 flex-1 border-slate-800 bg-slate-950 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{types.map((t) => <SelectItem key={t} value={t} className="text-xs capitalize">{t}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={status} onValueChange={(v) => setFilters({ status: v })}>
            <SelectTrigger className="h-7 flex-1 border-slate-800 bg-slate-950 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{statuses.map((s) => <SelectItem key={s} value={s} className="text-xs capitalize">{s}</SelectItem>)}</SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            aria-pressed={reviewOnly}
            onClick={() => setFilters({ reviewOnly: !reviewOnly })}
            className={cn('h-7 border-slate-800 px-2 text-xs', reviewOnly ? 'bg-amber-500/10 text-amber-300 border-amber-500/30' : 'bg-slate-950 text-slate-400')}
          >
            <AlertTriangle className="mr-1 h-3.5 w-3.5" /> Review
          </Button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-slate-900 shadow-sm shadow-slate-950">
            <TableRow className="border-slate-800 hover:bg-transparent">
              {COLS.map(({ key, label }) => (
                <TableHead
                  key={key}
                  role="columnheader"
                  aria-sort={sort.col === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  tabIndex={0}
                  className="text-slate-400 cursor-pointer select-none hover:text-slate-200"
                  onClick={() => toggleSort(key)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSort(key) } }}
                >
                  {label}<SortIcon col={key} sort={sort} />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {paddingTop > 0 && <tr aria-hidden="true"><td colSpan={COLS.length} style={{ height: paddingTop }} /></tr>}
            {vItems.map((vi) => {
              const a = rows[vi.index]
              return (
                <TableRow
                  key={a.asset_id}
                  data-index={vi.index}
                  ref={virtualizer.measureElement}
                  onClick={() => onSelect?.(a)}
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect?.(a) } }}
                  className={cn('cursor-pointer border-slate-800 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-sky-500/50', selectedId === a.asset_id ? 'bg-sky-500/10 ring-1 ring-inset ring-sky-500/30' : 'hover:bg-slate-800/50')}
                >
                  <TableCell className="max-w-[190px] align-top">
                    <div className="truncate text-xs font-medium text-slate-200">{a.asset_name}</div>
                    <div className="mt-1 truncate text-[10px] text-slate-500">{a.operator || a.asset_id}</div>
                  </TableCell>
                  <TableCell className="align-top"><Badge variant="outline" className={cn('text-[10px]', typeMeta(a.asset_type).badge)}>{typeMeta(a.asset_type).label}</Badge></TableCell>
                  <TableCell className="align-top text-xs text-slate-400">{a.municipality || '—'}</TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-wrap gap-1">
                      {a.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(a.evidence_tier))}>{a.evidence_tier}</Badge>}
                      <span {...statusTone(a.status, 'text-[10px] capitalize')}>{a.status || 'unknown'}</span>
                      {needsReview(a) && <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">review</Badge>}
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
            {paddingBottom > 0 && <tr aria-hidden="true"><td colSpan={COLS.length} style={{ height: paddingBottom }} /></tr>}
          </TableBody>
        </Table>
        {rows.length === 0 && (
          <div className="flex h-40 items-center justify-center text-sm text-slate-500">No assets match the active filters.</div>
        )}
      </div>
    </div>
  )
}
