import { useMemo, useState } from 'react'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { tierBadge, fmtDate } from '@/lib/format'
import { typeMeta, statusBadge } from '@/lib/aguayluz-format'
import { cn } from '@/lib/utils'
import { ChevronDown, ChevronRight, Database, Link2, MapPin } from 'lucide-react'

function matchesAsset(event, asset) {
  if (!event || !asset) return false
  if ((event.linked_asset_ids || []).includes(asset.asset_id)) return true
  if (event.municipality && asset.municipality && event.municipality === asset.municipality) return true
  return false
}

export default function AssetDetail({ asset: a, events = [], onClose }) {
  const [rawOpen, setRawOpen] = useState(false)
  const linkedEvents = useMemo(() => events.filter((event) => matchesAsset(event, a)), [events, a])

  return (
    <Sheet open={!!a} onOpenChange={(o) => !o && onClose?.()}>
      <SheetContent className="w-full overflow-y-auto border-slate-800 bg-slate-950 text-slate-200 sm:max-w-xl">
        {a && (
          <>
            <SheetHeader>
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="outline" className={cn('text-[10px]', typeMeta(a.asset_type).badge)}>{typeMeta(a.asset_type).label}</Badge>
                <Badge variant="outline" className={cn('text-[10px] capitalize', statusBadge(a.status))}>{a.status || 'unknown'}</Badge>
                {a.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(a.evidence_tier))}>{a.evidence_tier}</Badge>}
                {a.review_status && <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">{a.review_status}</Badge>}
              </div>
              <SheetTitle className="text-left text-slate-100">{a.asset_name}</SheetTitle>
              <SheetDescription className="text-left text-slate-400">
                {a.asset_subtype || a.asset_type || 'utility asset'} · {a.municipality || 'municipio unavailable'}
              </SheetDescription>
            </SheetHeader>

            <div className="mt-5 space-y-4">
              <Section title="Identity">
                <Row k="Asset ID" v={a.asset_id} mono />
                <Row k="Type" v={a.asset_type} />
                <Row k="Subtype" v={a.asset_subtype} />
                <Row k="Infrastructure role" v={a.infrastructure_role || a.role} />
              </Section>

              <Section title="Location" icon={MapPin}>
                <Row k="Municipio" v={a.municipality} />
                <Row k="Zone / area" v={a.zone || a.affected_area} />
                <Row k="Coordinates" v={a.lat != null && a.lon != null ? `${a.lat}, ${a.lon}` : '—'} mono />
              </Section>

              <Section title="Operator / owner">
                <Row k="Operator" v={a.operator} />
                <Row k="Owner" v={a.owner} />
                <Row k="Agency" v={a.agency} />
              </Section>

              <Section title="Evidence / source" icon={Database}>
                <Row k="Evidence tier" v={a.evidence_tier} />
                <Row k="Confidence" v={a.confidence} />
                <Row k="Review status" v={a.review_status} />
                <Row k="Source" v={a.source_ref} />
                <Row k="Source hash" v={a.source_hash} mono />
              </Section>

              <Section title={`Linked events (${linkedEvents.length})`} icon={Link2}>
                {linkedEvents.length === 0 ? (
                  <p className="text-xs text-slate-500">No service events are directly linked or municipio-matched for this asset.</p>
                ) : (
                  <div className="space-y-2">
                    {linkedEvents.slice(0, 8).map((event) => (
                      <div key={event.event_id} className="rounded-md border border-slate-800 bg-slate-900 p-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium capitalize text-slate-200">{(event.event_type || 'event').replace(/_/g, ' ')}</span>
                          {event.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(event.evidence_tier))}>{event.evidence_tier}</Badge>}
                          <span className="ml-auto text-[10px] text-slate-500">{fmtDate(event.start_time)}</span>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-400">{event.affected_area || event.municipality || 'Area unavailable'}</p>
                      </div>
                    ))}
                    {linkedEvents.length > 8 && <p className="text-[11px] text-slate-500">+ {linkedEvents.length - 8} additional municipio-matched events</p>}
                  </div>
                )}
              </Section>

              <div className="rounded-lg border border-slate-800 bg-slate-900/60">
                <Button
                  variant="ghost"
                  className="flex w-full justify-start gap-2 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800"
                  onClick={() => setRawOpen((v) => !v)}
                >
                  {rawOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                  Raw record preview
                </Button>
                {rawOpen && (
                  <pre className="max-h-72 overflow-auto border-t border-slate-800 p-3 text-[11px] leading-relaxed text-slate-300">
                    {JSON.stringify(a, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function Section({ title, icon: Icon, children }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {Icon && <Icon className="h-3.5 w-3.5 text-sky-300" />}
        {title}
      </h3>
      <div className="space-y-2">{children}</div>
    </section>
  )
}

function Row({ k, v, mono = false }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-800/70 pb-1.5 last:border-b-0 last:pb-0">
      <dt className="text-xs text-slate-500">{k}</dt>
      <dd className={cn('max-w-[65%] break-words text-right text-xs text-slate-200', mono && 'font-mono text-[11px]')}>{v ?? '—'}</dd>
    </div>
  )
}
