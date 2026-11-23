import { useQuery } from '@tanstack/react-query'
import { API_BASE } from '@/lib/api'

export default function IonospherePage() {
  const query = useQuery({
    queryKey: ['ionosphere-status'],
    retry: false,
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/ionosphere/status`, { signal })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      return response.json()
    },
  })
  return <main className="p-6 space-y-4">
    <h1 className="text-2xl font-bold">Space weather / Clima espacial</h1>
    <p role="note">Preview: regional ionospheric context. No confirmed grid damage, service outage, or municipality measurements.</p>
    {query.isPending && <p role="status">Loading source audit…</p>}
    {query.isError && <p role="alert">Source audit unavailable: {query.error.message}</p>}
    <button className="border rounded px-3 py-2" onClick={() => query.refetch()} disabled={query.isFetching}>Retry / Reintentar</button>
    {query.data && <section aria-label="Ionosphere source audit" className="space-y-3">
      <p>Status: {query.data.state}; freshness: {query.data.freshness}</p>
      <p>TEC: {query.data.tec.state} — {query.data.tec.reason}</p>
      <p>ROTI: {query.data.roti.state} — {query.data.roti.reason}</p>
      {query.data.roti.audit && <section aria-label="ROTI acquisition audit">
        <h2 className="text-xl">ROTI source review / Revisión de fuente</h2>
        <p>Captured interval: {query.data.roti.audit.interval_raw.start_time} to {query.data.roti.audit.interval_raw.end_time} UTC. Metadata only; not a live ROTI feed.</p>
        <p>{query.data.roti.audit.reported_link_feature_count} source-reported link points; {query.data.roti.audit.bbox_candidate_points} regional discovery candidates. Receiver locations and canonical geographic mappings remain unresolved.</p>
        <p>Matrix audit: {query.data.roti.audit.matrix_axis_diagnostic.unresolved_bins} unexplained occupied bins. Numeric rendering remains withheld.</p>
        <p className="break-all">Captured source SHA-256: {query.data.roti.audit.raw_sha256}</p>
        <a className="underline" href={query.data.roti.audit.license}>DLR scientific-use and redistribution terms</a>
        <p>{query.data.roti.audit.credit}</p>
      </section>}
      {query.data.roti.audit_error && <p role="alert">ROTI audit unavailable: {query.data.roti.audit_error}</p>}
      <p>GloTEC model grid: {query.data.tec.resolution_degrees.join('° × ')}°. Units: TECU.</p>
      <p>Acquisition audit: {query.data.acquisition_attempt.date}; HTTP {query.data.acquisition_attempt.http_status}. This is a historical attempt, not a live health check.</p>
      <a className="underline" href={query.data.source_url} target="_blank" rel="noreferrer">NOAA source documentation</a>
      {query.data.archive?.state === 'ARCHIVED_SNAPSHOT' && <section aria-label="Archived TEC context" className="space-y-2">
        <h2 className="text-xl">Archived TEC model / Modelo TEC archivado</h2>
        <p>{query.data.archive.freshness}; observation UTC: {query.data.archive.observed_at}</p>
        <p>Regional discovery window only. Grid points are not municipality measurements. Quality flags are source-reported observation support, not confidence percentages.</p>
        <p>Selected {query.data.archive.selected_count}; excluded {query.data.archive.excluded_count}; total {query.data.archive.total_features}.</p>
        <a className="underline" href={query.data.archive.source_url}>Captured NOAA product</a>
        <p className="break-all">Source SHA-256: {query.data.archive.source_sha256}</p>
        {query.data.archive.producer_transport && <p>Frozen source exchange: {query.data.archive.producer_transport.state}; {query.data.archive.producer_transport.record_count} persisted records validated. Producer revision: {query.data.archive.producer_transport.producer_commit ?? 'not supplied'}.</p>}
        {query.data.archive.reference_coverage && <details>
          <summary>Reference geometry coverage / Cobertura de referencia</summary>
          <p>{query.data.archive.reference_coverage.state}: {query.data.archive.reference_coverage.classified_count} of {query.data.archive.reference_coverage.reference_count} frozen generalized references classified. This is coordinate-envelope coverage, not station support or measurement precision.</p>
          <table aria-label="Municipio reference coverage"><thead><tr><th>GEOID</th><th>Source name</th><th>Spatial state</th></tr></thead><tbody>
            {query.data.archive.reference_coverage.rows.map(row => <tr key={row.source_properties.geoid}><td>{row.source_properties.geoid}</td><td>{row.source_properties.name}</td><td>{row.source_node_envelope}</td></tr>)}
          </tbody></table>
        </details>}
        <table aria-label="Archived TEC grid points"><thead><tr><th>Longitude</th><th>Latitude</th><th>TEC (TECU)</th><th>Raw quality flag</th></tr></thead>
          <tbody>{query.data.archive.rows.map(row => <tr key={row.source_feature_index}>
            <td>{row.longitude}</td><td>{row.latitude}</td><td>{row.raw_feature.properties.tec ?? 'MISSING'}</td><td>{row.raw_feature.properties.quality_flag}</td>
          </tr>)}</tbody>
        </table>
      </section>}
      {query.data.archive?.state === 'BLOCKED' && <p role="alert">Archived snapshot unavailable: {query.data.archive.error}</p>}
    </section>}
  </main>
}
