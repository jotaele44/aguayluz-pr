import { useState } from 'react'
import { useAssets } from '@/lib/hooks'
import AssetsTable from '@/components/AssetsTable'
import AssetDetail from '@/components/AssetDetail'
import ErrorBoundary from '@/components/ErrorBoundary'

export default function AssetsPage() {
  const { data: assets = [], isLoading } = useAssets()
  const [selected, setSelected] = useState(null)

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-slate-800 shrink-0">
        <h1 className="text-lg font-semibold text-slate-100">Assets</h1>
        <p className="text-xs text-slate-500 mt-0.5">All tracked infrastructure assets across Puerto Rico</p>
      </div>
      <div className="flex-1 min-h-0">
        <ErrorBoundary label="Assets">
          <AssetsTable assets={assets} isLoading={isLoading} selectedId={selected?.asset_id} onSelect={setSelected} />
        </ErrorBoundary>
      </div>
      <AssetDetail asset={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
