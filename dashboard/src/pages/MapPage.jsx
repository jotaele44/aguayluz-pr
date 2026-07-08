import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAssets, useAssetsGeojson, useMunicipiosGeojson, useEvents } from '@/lib/hooks'
import AssetMap from '@/components/AssetMap'
import AssetsTable from '@/components/AssetsTable'
import AssetDetail from '@/components/AssetDetail'
import ErrorBoundary from '@/components/ErrorBoundary'

export default function MapPage() {
  const { data: assets = [], isLoading } = useAssets()
  const { data: assetsGeo } = useAssetsGeojson()
  const { data: municipios } = useMunicipiosGeojson()
  const { data: events = [] } = useEvents()
  const [selected, setSelected] = useState(null)
  const [selectedMunicipio, setSelectedMunicipio] = useState(null)
  const [searchParams] = useSearchParams()

  // fly-to from ?flyTo=ASSET_ID&lat=...&lon=... (set by AssetDetail "Show on map")
  const flyToLat = parseFloat(searchParams.get('lat'))
  const flyToLon = parseFloat(searchParams.get('lon'))
  const flyToId = searchParams.get('flyTo')

  const selectByProps = (props) => {
    const full = assets.find((a) => a.asset_id === props.asset_id)
    setSelected(full ?? props)
  }

  return (
    <div className="flex h-full">
      <div className="relative flex-1 min-w-0">
        <AssetMap
          assets={assetsGeo}
          assetRows={assets}
          municipios={municipios}
          events={events}
          selectedAssetId={selected?.asset_id}
          selectedMunicipio={selectedMunicipio}
          onSelect={selectByProps}
          onMunicipioSelect={setSelectedMunicipio}
          flyTo={flyToId && !isNaN(flyToLat) && !isNaN(flyToLon) ? { id: flyToId, lat: flyToLat, lon: flyToLon } : null}
        />
        <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-slate-900/80 px-2 py-1 text-[11px] text-slate-400">
          {assetsGeo?.features?.length ?? 0} mapped assets · {selectedMunicipio?.name ? `${selectedMunicipio.name} selected` : 'colored by type'}
        </div>
      </div>

      <aside className="w-[440px] shrink-0 border-l border-slate-800 bg-slate-950 flex flex-col min-h-0">
        <div className="border-b border-slate-800 px-3 py-2">
          <div className="text-xs font-semibold text-slate-200">Assets</div>
          <div className="text-[11px] text-slate-500">Select a row or map marker for details · outages, monitoring, and review each have their own page</div>
        </div>
        <div className="flex-1 min-h-0">
          <ErrorBoundary label="Assets">
            <AssetsTable assets={assets} isLoading={isLoading} selectedId={selected?.asset_id} onSelect={setSelected} />
          </ErrorBoundary>
        </div>
      </aside>

      <AssetDetail asset={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
