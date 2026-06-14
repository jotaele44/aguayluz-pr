import { useMemo, useState } from 'react'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { tierBadge } from '@/lib/format'
import { typeMeta, statusBadge } from '@/lib/aguayluz-format'
import { cn } from '@/lib/utils'

export default function AssetsTable({ assets = [], selectedId, onSelect }) {
  const [type, setType] = useState('all')
  const [q, setQ] = useState('')

  const types = useMemo(
    () => ['all', ...Array.from(new Set(assets.map((a) => a.asset_type).filter(Boolean)))],
    [assets],
  )
  const rows = assets.filter((a) =>
    (type === 'all' || a.asset_type === type) &&
    (!q || (a.asset_name || '').toLowerCase().includes(q.toLowerCase()) || (a.municipality || '').toLowerCase().includes(q.toLowerCase())))

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 p-2">
        <span className="text-xs text-slate-400 shrink-0 w-10">{rows.length}</span>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search asset / municipio…" className="h-7 flex-1 text-xs bg-slate-950 border-slate-800" />
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="h-7 w-[120px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>{types.map((t) => <SelectItem key={t} value={t} className="text-xs capitalize">{t}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 bg-slate-900 z-10">
            <TableRow className="hover:bg-transparent border-slate-800">
              <TableHead className="text-slate-400">Asset</TableHead>
              <TableHead className="text-slate-400">Type</TableHead>
              <TableHead className="text-slate-400">Municipio</TableHead>
              <TableHead className="text-slate-400">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((a) => (
              <TableRow
                key={a.asset_id}
                onClick={() => onSelect?.(a)}
                className={cn('cursor-pointer border-slate-800', selectedId === a.asset_id ? 'bg-sky-500/10' : 'hover:bg-slate-800/50')}
              >
                <TableCell className="text-xs text-slate-200 max-w-[200px] truncate">{a.asset_name}</TableCell>
                <TableCell><Badge variant="outline" className={cn('text-[10px]', typeMeta(a.asset_type).badge)}>{typeMeta(a.asset_type).label}</Badge></TableCell>
                <TableCell className="text-xs text-slate-400">{a.municipality || '—'}</TableCell>
                <TableCell><Badge variant="outline" className={cn('text-[10px] capitalize', statusBadge(a.status))}>{a.status}</Badge></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
