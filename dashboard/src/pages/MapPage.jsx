import { useState } from 'react'
import { useAssets, useAssetsGeojson, useMunicipiosGeojson } from '@/lib/hooks'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import AssetMap from '@/components/AssetMap'
import AssetsTable from '@/components/AssetsTable'
import OutagesPanel from '@/components/OutagesPanel'
import MonitoringCharts from '@/components/MonitoringCharts'
import ReviewQueue from '@/components/ReviewQueue'
import AssetDetail from '@/components/AssetDetail'
import ErrorBoundary from '@/components/ErrorBoundary'

export default function MapPage() {
  const { data: assets = [], isLoading } = useAssets()
  const { data: assetsGeo } = useAssetsGeojson()
  const { data: municipios } = useMunicipiosGeojson()
  const [selected, setSelected] = useState(null)

  const selectByProps = (props) => {
    const full = assets.find((a) => a.asset_id === props.asset_id)
    setSelected(full ?? props)
  }

  return (
    <div className="flex h-full">
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
            <ErrorBoundary label="Assets">
              <AssetsTable assets={assets} isLoading={isLoading} selectedId={selected?.asset_id} onSelect={setSelected} />
            </ErrorBoundary>
          </TabsContent>
          <TabsContent value="outages" className="flex-1 min-h-0 mt-2">
            <ErrorBoundary label="Outages"><OutagesPanel /></ErrorBoundary>
          </TabsContent>
          <TabsContent value="monitoring" className="flex-1 min-h-0 mt-2">
            <ErrorBoundary label="Monitoring"><MonitoringCharts /></ErrorBoundary>
          </TabsContent>
          <TabsContent value="review" className="flex-1 min-h-0 mt-2">
            <ErrorBoundary label="Review Queue"><ReviewQueue /></ErrorBoundary>
          </TabsContent>
        </Tabs>
      </aside>

      <AssetDetail asset={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
