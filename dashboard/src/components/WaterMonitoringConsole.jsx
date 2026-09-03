import { useMemo, useState } from 'react'
import { Layers3, Map, ShieldCheck, Waves } from 'lucide-react'
import MonitoringCharts from '@/components/MonitoringCharts'
import IncidentOperationsConsole from '@/components/IncidentOperationsConsole'
import { WATER_MONITORING_LAYERS, isCertifiableLayer } from '@/lib/water-monitoring'

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
  const certifiable = isCertifiableLayer(layer)
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
            {certifiable ? 'LIVE SERIES CONTRACT PRESENT' : 'NOT CERTIFIABLE YET'}
          </div>
        </div>
      </div>

      <div className="grid gap-3 p-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-h-[360px] rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
            <Map className="h-4 w-4 text-sky-300" /> Hydrologic map workspace
          </div>
          <p className="mt-2 max-w-2xl text-[11px] leading-relaxed text-slate-500">
            This workspace is reserved for authoritative station, reservoir, watershed, rainfall, groundwater, coastal, and extraction geometry. Geometry is not synthesized from names or nearest-neighbor guesses. Until each adapter supplies certified geometry, the layer remains explicitly partial or planned.
          </p>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {layer.series.length ? layer.series.map((series) => (
              <div key={series} className="rounded border border-slate-800 bg-slate-950 p-2.5">
                <div className="text-[10px] uppercase tracking-wide text-slate-500">Bound series</div>
                <div className="mt-1 font-mono text-xs text-sky-300">{series}</div>
              </div>
            )) : (
              <div className="rounded border border-dashed border-slate-700 bg-slate-950 p-3 text-[11px] text-slate-500 sm:col-span-2 lg:col-span-3">
                No live metric is exposed for this layer until source, identity, unit, temporal, and geometry gates close.
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
            <ShieldCheck className="h-4 w-4 text-emerald-300" /> Certification boundary
          </div>
          <dl className="mt-3 space-y-2 text-[11px]">
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Layer state</dt><dd className="font-mono text-slate-300">{layer.state}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Metric contract</dt><dd className="font-mono text-slate-300">{layer.series.length ? 'PRESENT' : 'OPEN'}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Legal inference</dt><dd className="font-mono text-slate-300">FAIL-CLOSED</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Synthetic geometry</dt><dd className="font-mono text-slate-300">PROHIBITED</dd></div>
          </dl>
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
      <MonitoringWorkspace layer={layer} />
    </div>
  )
}
