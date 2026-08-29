import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAssets, useAssetsGeojson, useMunicipiosGeojson, useBarriosGeojson, useEvents, useEventDensity, useAlertsGeojson, useCoverage, useReadingsEnvelope } from '@/lib/hooks'
import AssetMap from '@/components/AssetMap'
import AssetsTable from '@/components/AssetsTable'
import AssetDetail from '@/components/AssetDetail'
import ErrorBoundary from '@/components/ErrorBoundary'

export default function MapPage() {
  const { data: assets = [], isLoading } = useAssets()
  const { data: assetsGeo } = useAssetsGeojson()
  const { data: municipios } = useMunicipiosGeojson()
  const { data: barrios } = useBarriosGeojson()
  const { data: events = [] } = useEvents()
  // Aggregated over the full, uncapped corpus (unlike `events` above, which is
  // paginated for the map's point layer) — this is what drives the "Density"
  // municipio fill mode, since individual events are structurally area-level.
  const { data: eventDensity } = useEventDensity()
  const eventDensityByGeoid = eventDensity?.by_geoid ?? {}
  const { data: alertsGeo } = useAlertsGeojson()
  const { data: coverage } = useCoverage()
  // drought_category's `site_no` is the municipio's FIPS, which is also
  // pr_municipios.geojson's `geoid` (scripts/ingest_drought_usdm.py) — the one series
  // where a real municipio-wide choropleth tint is honest rather than invented.
  const { data: droughtEnvelope } = useReadingsEnvelope({ kind: 'drought', metric: 'drought_category' })
  const [selected, setSelected] = useState(null)
  const [selectedMunicipio, setSelectedMunicipio] = useState(null)
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const droughtByGeoid = useMemo(() => {
    const latest = new Map()
    for (const row of droughtEnvelope?.items ?? []) {
      const geoid = row.site_no
      if (!geoid) continue
      const current = latest.get(geoid)
      if (!current || String(row.observed_date || '') > String(current.observed_date || '')) {
        latest.set(geoid, row)
      }
    }
    return Object.fromEntries([...latest].map(([geoid, row]) => [geoid, row.value]))
  }, [droughtEnvelope])

  // fly-to from ?flyTo=ASSET_ID&lat=...&lon=... (set by AssetDetail "Show on map")
  const flyToLat = parseFloat(searchParams.get('lat'))
  const flyToLon = parseFloat(searchParams.get('lon'))
  const flyToId = searchParams.get('flyTo')

  const selectByProps = useCallback((props) => {
    setSelected(assets.find((a) => a.asset_id === props.asset_id) ?? props)
  }, [assets])

  const mapped = assetsGeo?.features?.length ?? 0
  const unmapped = coverage?.assets?.unmapped ?? 0

  return (
    <div className="flex h-full">
      <div className="relative flex-1 min-w-0">
        <AssetMap
          assets={assetsGeo}
          assetRows={assets}
          municipios={municipios}
          barrios={barrios}
          events={events}
          alerts={alertsGeo}
          droughtByGeoid={droughtByGeoid}
          eventDensityByGeoid={eventDensityByGeoid}
          selectedAssetId={selected?.asset_id}
          selectedMunicipio={selectedMunicipio}
          onSelect={selectByProps}
          onMunicipioSelect={(props) => {
            setSelectedMunicipio(props)
            navigate(`/municipios/${encodeURIComponent(props.name)}`)
          }}
          onAlertSelect={(props) => navigate(`/alerts/${encodeURIComponent(props.alert_id)}`)}
          flyTo={flyToId && !isNaN(flyToLat) && !isNaN(flyToLon) ? { id: flyToId, lat: flyToLat, lon: flyToLon } : null}
        />
        {/* State the denominator: 43% of the corpus (canal segments, historic aqueduct
            alignments) has no geometry, so a bare "N mapped assets" reads as "N assets". */}
        <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-slate-900/80 px-2 py-1 text-[11px] text-slate-400">
          {mapped} of {coverage?.assets?.total ?? assets.length} assets mapped
          {unmapped > 0 && <span className="text-slate-500"> · {unmapped} without geometry</span>}
          {' · '}{selectedMunicipio?.name ? `${selectedMunicipio.name} selected` : 'colored by type'}
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
