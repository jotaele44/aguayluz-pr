import { useState } from 'react'
import { useAssets } from '@/lib/hooks'
import AssetsTable from '@/components/AssetsTable'
import AssetDetail from '@/components/AssetDetail'
import ErrorBoundary from '@/components/ErrorBoundary'
import PageHeader from '@/components/common/PageHeader'

export default function AssetsPage() {
  const { data: assets = [], isLoading } = useAssets()
  const [selected, setSelected] = useState(null)

  return (
    <div className="flex flex-col h-full">
      <PageHeader title="Assets" subtitle="All tracked infrastructure assets across Puerto Rico" />
      <div className="flex-1 min-h-0">
        <ErrorBoundary label="Assets">
          <AssetsTable assets={assets} isLoading={isLoading} selectedId={selected?.asset_id} onSelect={setSelected} />
        </ErrorBoundary>
      </div>
      <AssetDetail asset={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
