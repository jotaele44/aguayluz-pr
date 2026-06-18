import { useState } from 'react'
import { useAssets, useAssetsGeojson, useMunicipiosGeojson } from '@/lib/hooks'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import AssetMap from '@/components/AssetMap'
import StatsBar from '@/components/StatsBar'
import AssetsTable from '@/components/AssetsTable'
import OutagesPanel from '@/components/OutagesPanel'
import MonitoringCharts from '@/components/MonitoringCharts'
import ReviewQueue from '@/components/ReviewQueue'
import AssetDetail from '@/components/AssetDetail'
import { Droplets } from 'lucide-react'

export default function Dashboard() {
  const { data: assets = [] } = useAssets()
  const { data: assetsGeo } = useAssetsGeojson()
  const { data: municipios } = useMunicipiosGeojson()
  const [selected, setSelected] = useState(null)

  const selectByProps = (props) => {
    const full = assets.find((a) => a.asset_id === props.asset_id)
    setSelected(full ?? props)
  }

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-200">
      <header className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-800 bg-slate-900">
        <Droplets className="h-5 w-5 text-sky-400" />
        <div>
          <h1 className="text-sm font-semibold text-slate-100 leading-none">AguaYLuz-PR</h1>
          <p className="text-[11px] text-slate-500 mt-0.5">Puerto Rico water & power continuity intelligence</p>
        </div>
      </header>

      <StatsBar />

      <div className="flex flex-1 min-h-0">
        <div className="relative flex-1 min-w-0">
          <AssetMap assets={assetsGeo} municipios={municipios} onSelect={selectByProps} />
          <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-slate-900/80 px-2 py-1 text-[11px] text-slate-400">
            {assetsGeo?.features?.length ?? 0} mapped assets · colored by type
          </div>
        </div>

        <aside className="w-[440px] shrink-0 border-l border-slate-800 bg-slate-950 flex flex-col min-h-0">
          <Tabs defaultValue="assets" className="flex flex-col flex-1 min-h-0">
            <TabsList className="grid grid-cols-4 mx-2 mt-2 bg-slate-900">
              <TabsTrigger value="assets" className="text-xs">Assets</TabsTrigger>
              <TabsTrigger value="outages" className="text-xs">Outages</TabsTrigger>
              <TabsTrigger value="monitoring" className="text-xs">Monitoring</TabsTrigger>
              <TabsTrigger value="review" className="text-xs">Review</TabsTrigger>
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

      <AssetDetail asset={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
