import { useMemo, useState } from 'react'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { tierBadge } from '@/lib/format'
import { typeMeta, statusBadge } from '@/lib/aguayluz-format'
import { cn } from '@/lib/utils'
import { AlertTriangle, FilterX } from 'lucide-react'

function normalized(value) {
  return `${value ?? ''}`.toLowerCase()
}

function needsReview(asset) {
  return asset.review_status === 'needs_review' || asset.status === 'needs_review' || asset.review_status === 'review'
}

export default function AssetsTable({ assets = [], selectedId, onSelect }) {
  const [type, setType] = useState('all')
  const [status, setStatus] = useState('all')
  const [reviewOnly, setReviewOnly] = useState(false)
  const [q, setQ] = useState('')

  const types = useMemo(
    () => ['all', ...Array.from(new Set(assets.map((a) => a.asset_type).filter(Boolean))).sort()],
    [assets],
  )
  const statuses = useMemo(
    () => ['all', ...Array.from(new Set(assets.map((a) => a.status).filter(Boolean))).sort()],
    [assets],
  )

  const rows = useMemo(() => assets.filter((a) => {
    const haystack = [a.asset_name, a.municipality, a.operator, a.asset_type, a.asset_subtype, a.source_ref, a.asset_id]
      .map(normalized)
      .join(' ')
    return (
      (type === 'all' || a.asset_type === type) &&
      (status === 'all' || a.status === status) &&
      (!reviewOnly || needsReview(a)) &&
      (!q || haystack.includes(normalized(q)))
    )
  }), [assets, type, status, reviewOnly, q])

  const clear = () => {
    setType('all')
    setStatus('all')
    setReviewOnly(false)
    setQ('')
  }

  return (
    <div className="flex flex-col h-full">
      <div className="space-y-2 border-b border-slate-900 px-2 pb-2">
        <div className="flex items-center gap-2">
          <div className="w-12 shrink-0 text-xs text-slate-400">{rows.length}</div>
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search asset, municipio, operator, source…"
            className="h-8 flex-1 border-slate-800 bg-slate-950 text-xs"
          />
          <Button size="sm" variant="outline" onClick={clear} className="h-8 border-slate-800 bg-slate-950 px-2 text-xs text-slate-400 hover:text-slate-100">
            <FilterX className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <Select value={type} onValueChange={setType}>
            <SelectTrigger className="h-7 flex-1 border-slate-800 bg-slate-950 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{types.map((t) => <SelectItem key={t} value={t} className="text-xs capitalize">{t}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="h-7 flex-1 border-slate-800 bg-slate-950 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{statuses.map((s) => <SelectItem key={s} value={s} className="text-xs capitalize">{s}</SelectItem>)}</SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setReviewOnly((v) => !v)}
            className={cn('h-7 border-slate-800 px-2 text-xs', reviewOnly ? 'bg-amber-500/10 text-amber-300 border-amber-500/30' : 'bg-slate-950 text-slate-400')}
          >
            <AlertTriangle className="mr-1 h-3.5 w-3.5" /> Review
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-slate-900 shadow-sm shadow-slate-950">
            <TableRow className="border-slate-800 hover:bg-transparent">
              <TableHead className="text-slate-400">Asset</TableHead>
              <TableHead className="text-slate-400">Type</TableHead>
              <TableHead className="text-slate-400">Municipio</TableHead>
              <TableHead className="text-slate-400">Evidence</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((a) => (
              <TableRow
                key={a.asset_id}
                onClick={() => onSelect?.(a)}
                className={cn('cursor-pointer border-slate-800', selectedId === a.asset_id ? 'bg-sky-500/10 ring-1 ring-inset ring-sky-500/30' : 'hover:bg-slate-800/50')}
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
                    <Badge variant="outline" className={cn('text-[10px] capitalize', statusBadge(a.status))}>{a.status || 'unknown'}</Badge>
                    {needsReview(a) && <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">review</Badge>}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {rows.length === 0 && (
          <div className="flex h-40 items-center justify-center text-sm text-slate-500">No assets match the active filters.</div>
        )}
      </div>
    </div>
  )
}
