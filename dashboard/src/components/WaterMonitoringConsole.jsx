import { useMemo, useState } from 'react'
import { Layers3, MapPinned, ShieldCheck, Waves } from 'lucide-react'
import MonitoringCharts from '@/components/MonitoringCharts'
import IncidentOperationsConsole from '@/components/IncidentOperationsConsole'
import AssetMap from '@/components/AssetMap'
import { useAssets, useAssetsGeojson, useMunicipiosGeojson } from '@/lib/hooks'
import {
  WATER_MONITORING_LAYERS,
  filterLayerAssetGeojson,
  filterLayerAssetRows,
  isCertifiableLayer,
} from '@/lib/water-monitoring'

const toneByState = {
  AVAILABLE: 'border-emerald-900/60 bg-emerald-950/20 text-emerald-300',
  PARTIAL: 'border-amber-900/60 bg-amber-950/20 text-amber-300',
  PLANNED: 'border-slate-700 bg-slate-900 text-slate-400',
  BLOCKED: 'border-red-900/60 bg-red-950/20 text-red-300',
}

function LayerRail({ selected, onSelect }) {
  return (
    <aside className="w-[250px] shrink-0 border-r border-slate-800 bg-slate-950 p-3 overflow-auto">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
        <Layers3 className="h-4 w-4" /> Water layers
      </div>
      <div className="space-y-2">
        {WATER_MONITORING_LAYERS.map((layer) => (
          <button
            key={layer.key}
            type="button"
            onClick={() => onSelect(layer.key)}
            className={`w-full rounded-lg border p-2.5 text-left transition ${selected === layer.key ? 'border-sky-700 bg-sky-950/25' : 'border-slate-800 bg-slate-900/50 hover:border-slate-700'}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-slate-200">{layer.label}</span>
              <span className={`rounded border px-1.5 py-0.5 text-[9px] ${toneByState[layer.state]}`}>{layer.state}</span>
            </div>
            <p className="mt-1.5 text-[10px] leading-relaxed text-slate-500">{layer.note}</p>
          </button>
        ))}
      </div>
    </aside>
  )
}

function MonitoringWorkspace({ layer }) {
  const { data: assets = [] } = useAssets()
  const { data: assetsGeo } = useAssetsGeojson()
  const { data: municipios } = useMunicipiosGeojson()
  const [selectedAsset, setSelectedAsset] = useState(null)

  const certifiable = isCertifiableLayer(layer)
  const mappedAssets = useMemo(() => filterLayerAssetGeojson(assetsGeo, layer), [assetsGeo, layer])
  const assetRows = useMemo(() => filterLayerAssetRows(assets, layer), [assets, layer])
  const selectedId = selectedAsset?.asset_id ?? selectedAsset?.id

  return (
    <section className="flex-1 min-w-0 overflow-auto bg-slate-950">
      <div className="border-b border-slate-800 bg-slate-900/40 p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <Waves className="h-4 w-4 text-sky-300" /> {layer.label}
            </div>
            <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-slate-500">{layer.note}</p>
          </div>
          <div className={`rounded border px-2 py-1 text-[10px] ${certifiable ? toneByState.AVAILABLE : toneByState[layer.state]}`}>
            {certifiable ? 'SERIES + GEOMETRY CONTRACT PASS' : 'NOT CERTIFIABLE YET'}
          </div>
        </div>
      </div>

      <div className="grid gap-3 p-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-h-[430px] overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40">
          <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <MapPinned className="h-4 w-4 text-sky-300" /> Hydrologic map
            </div>
            <div className="font-mono text-[10px] text-slate-500">
              {mappedAssets.features.length} mapped / {assetRows.length} bound assets
            </div>
          </div>
          {layer.geometryStatus === 'PASS' ? (
            <div className="h-[390px]">
              <AssetMap
                assets={mappedAssets}
                assetRows={assetRows}
                municipios={municipios}
                events={[]}
                alerts={null}
                droughtByGeoid={{}}
                selectedAssetId={selectedId}
                selectedMunicipio={null}
                onSelect={setSelectedAsset}
                onMunicipioSelect={() => {}}
                onAlertSelect={() => {}}
                flyTo={null}
              />
            </div>
          ) : (
            <div className="flex h-[390px] items-center justify-center p-6 text-center">
              <div className="max-w-xl rounded border border-dashed border-slate-700 bg-slate-950 p-4 text-[11px] leading-relaxed text-slate-500">
                Geometry is {layer.geometryStatus}. No fallback points, centroids, nearest-neighbor bindings, or name-derived geometry are rendered. This layer remains outside the certifiable map set until its authoritative geometry contract closes.
              </div>
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <ShieldCheck className="h-4 w-4 text-emerald-300" /> Certification boundary
            </div>
            <dl className="mt-3 space-y-2 text-[11px]">
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Layer state</dt><dd className="font-mono text-slate-300">{layer.state}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Series</dt><dd className="font-mono text-slate-300">{layer.seriesStatus}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Geometry</dt><dd className="font-mono text-slate-300">{layer.geometryStatus}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Bound subtype</dt><dd className="max-w-[190px] text-right font-mono text-slate-300">{layer.assetSubtypes.join(', ') || 'NONE'}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Legal inference</dt><dd className="font-mono text-slate-300">FAIL-CLOSED</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Synthetic geometry</dt><dd className="font-mono text-slate-300">PROHIBITED</dd></div>
            </dl>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Selected source manifestation</div>
            {selectedAsset ? (
              <dl className="mt-2 space-y-1.5 text-[11px]">
                <div><dt className="text-slate-600">Asset ID</dt><dd className="break-all font-mono text-sky-300">{selectedId ?? 'UNKNOWN'}</dd></div>
                <div><dt className="text-slate-600">Name</dt><dd className="text-slate-300">{selectedAsset.name ?? selectedAsset.asset_name ?? 'Unnamed'}</dd></div>
                <div><dt className="text-slate-600">Subtype</dt><dd className="font-mono text-slate-400">{selectedAsset.asset_subtype ?? 'UNKNOWN'}</dd></div>
              </dl>
            ) : (
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">Select a mapped source asset. Map selection does not create or strengthen entity identity; it only selects an already-bound manifestation.</p>
            )}
          </div>
        </div>
      </div>

      {certifiable && <MonitoringCharts />}
      <IncidentOperationsConsole />
    </section>
  )
}

export default function WaterMonitoringConsole() {
  const [layerKey, setLayerKey] = useState('rivers')
  const layer = useMemo(
    () => WATER_MONITORING_LAYERS.find((item) => item.key === layerKey) ?? WATER_MONITORING_LAYERS[0],
    [layerKey],
  )

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      <LayerRail selected={layer.key} onSelect={setLayerKey} />
      <MonitoringWorkspace key={layer.key} layer={layer} />
    </div>
  )
}
