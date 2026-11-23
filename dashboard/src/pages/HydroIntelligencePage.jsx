import { useEffect, useState } from 'react'
import { getHydroSourceReadiness } from '@/lib/hydro-intelligence-api'

export default function HydroIntelligencePage() {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  useEffect(() => {
    let alive = true
    getHydroSourceReadiness()
      .then((data) => { if (alive) setState({ loading: false, data, error: null }) })
      .catch((error) => { if (alive) setState({ loading: false, data: null, error: String(error) }) })
    return () => { alive = false }
  }, [])
  const { loading, data, error } = state
  return (
    <main className="p-6 space-y-5" data-testid="hydro-intelligence-readiness">
      <h1 className="text-2xl font-semibold text-slate-100">Hydroelectric Intelligence</h1>
      <p className="text-sm text-slate-400">Source acquisition readiness — not certified operational generation.</p>
      {loading && <p role="status">Loading authoritative source registry…</p>}
      {error && <p role="alert">Source readiness unavailable: {error}. No data was inferred.</p>}
      {data && (
        <>
          <div role="status" className="rounded border border-amber-600/50 bg-amber-950/20 p-3 text-sm text-amber-200">
            Certification: {data.certification}. Registry: {data.source_registry_state}.
            Automatic ingestion: {data.operational_ingestion ? 'enabled' : 'not verified / disabled'}.
          </div>
          <div className="overflow-x-auto">
            <table aria-label="Hydroelectric evidence sources" className="w-full text-left text-sm text-slate-300">
              <thead><tr className="border-b border-slate-700">
                <th className="p-2">Source</th><th className="p-2">Authority</th>
                <th className="p-2">Acquisition</th><th className="p-2">Parser</th>
                <th className="p-2">SHA-256</th></tr></thead>
              <tbody>{data.sources.map((source) => (
                <tr key={source.source_id} className="border-b border-slate-800">
                  <td className="p-2"><a className="underline" href={source.index_url} target="_blank" rel="noreferrer">{source.source_id}</a></td>
                  <td className="p-2">{source.authority}</td>
                  <td className="p-2">{source.acquisition_state}</td>
                  <td className="p-2">{source.parser_state}</td>
                  <td className="p-2 font-mono text-xs">{source.byte_sha256 ?? 'NOT FROZEN'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}
    </main>
  )
}
