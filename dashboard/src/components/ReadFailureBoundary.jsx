import { useCallback, useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'

const unavailable = (query) => query.meta?.blocksViewOnError !== false
  && query.isActive()
  && query.state.errorUpdateCount > 0
  && query.state.status !== 'success'

export default function ReadFailureBoundary({ children }) {
  const client = useQueryClient()
  const cache = client.getQueryCache()
  const subscribe = useCallback((notify) => cache.subscribe(notify), [cache])
  const snapshot = useCallback(() => JSON.stringify(cache.getAll().filter(unavailable).map((query) => [
    query.queryHash, query.state.fetchStatus,
  ])), [cache])
  const failures = JSON.parse(useSyncExternalStore(subscribe, snapshot, snapshot))
  const retrying = failures.some(([, status]) => status === 'fetching')
  return <>
    {failures.length > 0 && <section role="alert" className="m-4 rounded-lg border border-amber-600 bg-slate-950 p-4 text-slate-100">
      <h2 className="font-semibold">Data unavailable</h2>
      <p className="mt-2 text-sm">Some data for this view could not be loaded. Results are hidden until the reads succeed; unavailable data does not mean zero records.</p>
      <button type="button" disabled={retrying} className="mt-3 rounded border border-slate-500 px-3 py-2 disabled:opacity-50"
        onClick={() => client.refetchQueries({ type: 'active', predicate: unavailable })}>
        {retrying ? 'Retrying data…' : 'Retry data'}
      </button>
    </section>}
    <div hidden={failures.length > 0}>{children}</div>
  </>
}
