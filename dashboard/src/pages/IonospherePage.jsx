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
      <p>GloTEC model grid: {query.data.tec.resolution_degrees.join('° × ')}°. Units: TECU.</p>
      <p>Acquisition audit: {query.data.acquisition_attempt.date}; HTTP {query.data.acquisition_attempt.http_status}. This is a historical attempt, not a live health check.</p>
      <a className="underline" href={query.data.source_url} target="_blank" rel="noreferrer">NOAA source documentation</a>
    </section>}
  </main>
}
