import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { tierBadge } from '@/lib/format'
import { typeMeta, statusBadge } from '@/lib/aguayluz-format'
import { cn } from '@/lib/utils'

export default function AssetDetail({ asset: a, onClose }) {
  return (
    <Sheet open={!!a} onOpenChange={(o) => !o && onClose?.()}>
      <SheetContent className="bg-slate-950 border-slate-800 text-slate-200 w-full sm:max-w-md overflow-y-auto">
        {a && (
          <>
            <SheetHeader>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className={cn('text-[10px]', typeMeta(a.asset_type).badge)}>{typeMeta(a.asset_type).label}</Badge>
                <Badge variant="outline" className={cn('text-[10px] capitalize', statusBadge(a.status))}>{a.status}</Badge>
                {a.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(a.evidence_tier))}>{a.evidence_tier}</Badge>}
              </div>
              <SheetTitle className="text-slate-100 text-left">{a.asset_name}</SheetTitle>
              <SheetDescription className="text-slate-400 text-left">{a.asset_subtype || a.asset_type} · {a.municipality || '—'}</SheetDescription>
            </SheetHeader>
            <dl className="mt-4 space-y-2 text-sm">
              <Row k="Operator" v={a.operator} />
              <Row k="Asset ID" v={a.asset_id} />
              <Row k="Coordinates" v={a.lat != null ? `${a.lat}, ${a.lon}` : '—'} />
              <Row k="Confidence" v={a.confidence} />
              <Row k="Review status" v={a.review_status} />
              <Row k="Source" v={a.source_ref} />
            </dl>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-900 pb-1.5">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-slate-200 text-right break-all">{v ?? '—'}</dd>
    </div>
  )
}
