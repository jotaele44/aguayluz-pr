import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { tierBadge, fmtDate, typeMeta, statusTone, eventTone } from '@/lib/format'
import { useAssetEvents, useFlagAsset } from '@/lib/hooks'
import { useToast } from '@/components/ui/use-toast'
import { cn } from '@/lib/utils'
import { ChevronDown, ChevronRight, Database, ExternalLink, Flag, Map, MapPin, Zap } from 'lucide-react'

function RelatedEvents({ assetId }) {
  const { data: events = [], isLoading } = useAssetEvents(assetId)
  if (isLoading) return <Skeleton className="h-12 w-full" />
  if (!events.length) return <p className="text-xs text-slate-500">No related events found</p>
  return (
    <div className="space-y-2">
      {events.slice(0, 8).map((e, i) => (
        <div key={e.event_id ?? i} className="rounded-md border border-slate-800 bg-slate-900 p-2">
          <div className="flex items-center gap-2">
            <Zap className={cn('h-3 w-3 shrink-0', eventTone(e.event_type))} />
            <span className="text-xs font-medium capitalize text-slate-200">{(e.event_type || '').replace(/_/g, ' ')}</span>
            {e.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(e.evidence_tier))}>{e.evidence_tier}</Badge>}
            <span className="ml-auto text-[10px] text-slate-500">{fmtDate(e.start_time)}</span>
          </div>
          <p className="mt-1 text-[11px] text-slate-400">{e.affected_area || e.municipality || 'Area unavailable'}</p>
        </div>
      ))}
      {events.length > 8 && <p className="text-[11px] text-slate-500">+ {events.length - 8} more events</p>}
    </div>
  )
}

export default function AssetDetail({ asset: a, onClose }) {
  const [rawOpen, setRawOpen] = useState(false)
  const { mutate: flagAsset, isPending: flagging } = useFlagAsset()
  const { toast } = useToast()
  const navigate = useNavigate()

  const canShowOnMap = a?.lat != null && a?.lon != null

  const handleShowOnMap = () => {
    if (!a) return
    onClose?.()
    navigate(`/map?flyTo=${encodeURIComponent(a.asset_id)}&lat=${a.lat}&lon=${a.lon}`)
  }

  useEffect(() => {
    if (!a) return
    const handler = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [a, onClose])

  const handleFlag = () => {
    if (!a) return
    const next = a.review_status === 'needs_review' ? 'accepted' : 'needs_review'
    flagAsset(
      { id: a.asset_id, reviewStatus: next },
      { onSuccess: () => toast({ title: next === 'needs_review' ? 'Flagged for review' : 'Flag cleared', description: a.asset_name }) }
    )
  }

  return (
    <Sheet open={!!a} onOpenChange={(o) => !o && onClose?.()}>
      <SheetContent className="w-full overflow-y-auto border-slate-800 bg-slate-950 text-slate-200 sm:max-w-xl">
        {a && (
          <>
            <SheetHeader>
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="outline" className={cn('text-[10px]', typeMeta(a.asset_type).badge)}>{typeMeta(a.asset_type).label}</Badge>
                <span {...statusTone(a.status, 'text-[10px] capitalize')}>{a.status || 'unknown'}</span>
                {a.evidence_tier && <Badge variant="outline" className={cn('text-[10px]', tierBadge(a.evidence_tier))}>{a.evidence_tier}</Badge>}
                {a.review_status && <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">{a.review_status}</Badge>}
                {canShowOnMap && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="ml-auto h-6 px-2 text-[10px] text-sky-400 border-sky-800 hover:bg-sky-950"
                    onClick={handleShowOnMap}
                    title="Fly to this asset on the map"
                  >
                    <Map className="h-3 w-3 mr-1" />
                    Show on map
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className={cn('h-6 px-2 text-[10px]', canShowOnMap ? '' : 'ml-auto', a.review_status === 'needs_review' ? 'text-amber-300 border-amber-700 bg-amber-950/30' : 'text-slate-400 border-slate-700')}
                  disabled={flagging}
                  onClick={handleFlag}
                  title="Flag this asset for human review"
                >
                  <Flag className="h-3 w-3 mr-1" />
                  {a.review_status === 'needs_review' ? 'Unflag' : 'Flag for review'}
                </Button>
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
                <Row k="Coordinates" v={a.lat != null && a.lon != null ? `${a.lat}, ${a.lon}` : null} mono />
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
                <SourceRow sourceRef={a.source_ref} />
                <Row k="Source hash" v={a.source_hash} mono />
              </Section>

              <Section title="Related events">
                <RelatedEvents assetId={a.asset_id} />
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

function SourceRow({ sourceRef }) {
  const isUrl = typeof sourceRef === 'string' && (sourceRef.startsWith('http://') || sourceRef.startsWith('https://'))
  return (
    <div className="flex justify-between gap-4 border-b border-slate-800/70 pb-1.5 last:border-b-0 last:pb-0">
      <dt className="text-xs text-slate-500">Source</dt>
      <dd className="max-w-[65%] break-words text-right text-xs text-slate-200">
        {isUrl
          ? <a href={sourceRef} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline flex items-center gap-1 justify-end">
              {sourceRef.replace(/^https?:\/\//, '').slice(0, 40)}…
              <ExternalLink className="h-3 w-3 shrink-0" />
            </a>
          : (sourceRef ?? '—')}
      </dd>
    </div>
  )
}
