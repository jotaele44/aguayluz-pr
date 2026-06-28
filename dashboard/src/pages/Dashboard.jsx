import { useMemo, useState } from 'react'
import {
  useAssets,
  useAssetsGeojson,
  useEvents,
  useHealth,
  useMunicipiosGeojson,
  useReviewQueue,
} from '@/lib/hooks'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import AssetMap from '@/components/AssetMap'
import StatsBar from '@/components/StatsBar'
import AssetsTable from '@/components/AssetsTable'
import OutagesPanel from '@/components/OutagesPanel'
import MonitoringCharts from '@/components/MonitoringCharts'
import ReviewQueue from '@/components/ReviewQueue'
import AssetDetail from '@/components/AssetDetail'
import { Badge } from '@/components/ui/badge'
import { Activity, Clock, Database, Droplets, Server } from 'lucide-react'

const OFFLINE = import.meta.env.VITE_OFFLINE === '1'

function HeaderMetric({ icon: Icon, label, value, tone = 'text-slate-300' }) {
  return (
    <div className="hidden sm:flex items-center gap-1.5 rounded-md border border-slate-800 bg-slate-950/60 px-2.5 py-1.5">
      <Icon className={`h-3.5 w-3.5 ${tone}`} />
      <div className="leading-none">
        <div className="text-xs font-semibold text-slate-100">{value}</div>
        <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
      </div>
    </div>
  )
}

function TabLabel({ label, count }) {
  return (
    <span className="flex items-center gap-1.5">
      <span>{label}</span>
      <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">{count ?? '–'}</span>
    </span>
  )
}

export default function Dashboard() {
  const { data: assets = [] } = useAssets()
  const { data: assetsGeo } = useAssetsGeojson()
  const { data: municipios } = useMunicipiosGeojson()
  const { data: health } = useHealth()
  const { data: events = [] } = useEvents()
  const { data: reviewQueue = [] } = useReviewQueue()
  const [selected, setSelected] = useState(null)
  const [selectedMunicipio, setSelectedMunicipio] = useState(null)
  const [loadedAt] = useState(() => new Date())

  const readingsCount = useMemo(() => {
    const readings = health?.counts?.readings
    if (!readings) return null
    return Object.values(readings).reduce((total, n) => total + Number(n || 0), 0)
  }, [health])

  const selectByProps = (props) => {
    const full = assets.find((a) => a.asset_id === props.asset_id)
    setSelected(full ?? props)
  }

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-200">
      <header className="border-b border-slate-800 bg-slate-950/95 shadow-lg shadow-slate-950/30">
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-sky-500/20 bg-sky-500/10">
              <Droplets className="h-5 w-5 text-sky-300" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-sm font-semibold text-slate-100">AguaYLuz-PR</h1>
                <Badge variant="outline" className="hidden sm:inline-flex border-emerald-500/30 bg-emerald-500/10 text-[10px] text-emerald-300">
                  real data partial
                </Badge>
                {OFFLINE && (
                  <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">
                    offline export
                  </Badge>
                )}
              </div>
              <p className="truncate text-[11px] text-slate-500">Puerto Rico water & power continuity intelligence</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <HeaderMetric icon={Server} label="backend" value={health?.status === 'ok' ? 'online' : 'down'} tone={health?.status === 'ok' ? 'text-emerald-300' : 'text-red-300'} />
            <HeaderMetric icon={Database} label="assets" value={health?.counts?.assets ?? assets.length ?? '–'} tone="text-sky-300" />
            <HeaderMetric icon={Activity} label="events" value={health?.counts?.events ?? events.length ?? '–'} tone="text-amber-300" />
            <HeaderMetric icon={Clock} label="loaded" value={loadedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} />
          </div>
        </div>
      </header>

      <StatsBar />

      <div className="flex flex-1 min-h-0">
        <div className="relative flex-1 min-w-0 border-r border-slate-900">
          <AssetMap
            assets={assetsGeo}
            assetRows={assets}
            municipios={municipios}
            events={events}
            selectedAssetId={selected?.asset_id}
            selectedMunicipio={selectedMunicipio}
            onSelect={selectByProps}
            onMunicipioSelect={setSelectedMunicipio}
          />
          <div className="pointer-events-none absolute bottom-2 left-2 rounded border border-slate-700/70 bg-slate-950/80 px-2 py-1 text-[11px] text-slate-300 shadow-lg backdrop-blur">
            {assetsGeo?.features?.length ?? 0} mapped assets · {selectedMunicipio?.name ? `${selectedMunicipio.name} selected` : 'colored by infrastructure type'}
          </div>
        </div>

        <aside className="w-[460px] shrink-0 border-l border-slate-800 bg-slate-950 flex flex-col min-h-0">
          <div className="border-b border-slate-800 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-xs font-semibold text-slate-200">Operational panel</div>
                <div className="text-[11px] text-slate-500">Review pressure, events, monitoring, and asset intelligence</div>
              </div>
              <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-300">
                {reviewQueue.length} review
              </Badge>
            </div>
          </div>

          <Tabs defaultValue="assets" className="flex flex-col flex-1 min-h-0">
            <TabsList className="grid grid-cols-4 mx-2 mt-2 bg-slate-900">
              <TabsTrigger value="assets" className="text-xs"><TabLabel label="Assets" count={assets.length} /></TabsTrigger>
              <TabsTrigger value="outages" className="text-xs"><TabLabel label="Outages" count={events.length} /></TabsTrigger>
              <TabsTrigger value="monitoring" className="text-xs"><TabLabel label="Monitor" count={readingsCount} /></TabsTrigger>
              <TabsTrigger value="review" className="text-xs"><TabLabel label="Review" count={reviewQueue.length} /></TabsTrigger>
            </TabsList>
            <TabsContent value="assets" className="flex-1 min-h-0 mt-2">
              <AssetsTable assets={assets} selectedId={selected?.asset_id} onSelect={setSelected} />
            </TabsContent>
            <TabsContent value="outages" className="flex-1 min-h-0 mt-2"><OutagesPanel /></TabsContent>
            <TabsContent value="monitoring" className="flex-1 min-h-0 mt-2"><MonitoringCharts /></TabsContent>
            <TabsContent value="review" className="flex-1 min-h-0 mt-2"><ReviewQueue /></TabsContent>
          </Tabs>
        </aside>
      </div>

      <AssetDetail asset={selected} events={events} onClose={() => setSelected(null)} />
    </div>
  )
}
