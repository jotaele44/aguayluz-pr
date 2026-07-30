import { useCallback, useEffect, useState } from 'react'
import { API_BASE, getApiKey } from '@/lib/api'

const authHeaders = () => {
  const key = getApiKey()
  return { 'Content-Type': 'application/json', ...(key ? { Authorization: `Bearer ${key}` } : {}) }
}

export default function IncidentOperationsConsole() {
  const [data, setData] = useState({ items: [], event_count: 0, replay_equals_materialized_state: true })
  const [selected, setSelected] = useState(null)
  const [actor, setActor] = useState('operator')
  const [reason, setReason] = useState('operator review')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/monitoring/incidents`)
      setData(res.ok ? await res.json() : { items: [], event_count: 0, replay_equals_materialized_state: false })
    } catch {
      setData({ items: [], event_count: 0, replay_equals_materialized_state: false })
    }
  }, [])

  useEffect(() => { load() }, [load])

  const transition = async (eventType) => {
    if (!selected) return
    setError('')
    const res = await fetch(`${API_BASE}/monitoring/incidents/${encodeURIComponent(selected)}/transitions`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ event_type: eventType, actor, reason, payload: {} }),
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      setError(`Transition failed (${res.status}): ${body.slice(0, 180)}`)
      return
    }
    await load()
  }

  return (
    <section className="m-3 rounded-lg border border-slate-800 bg-slate-900 p-3" aria-label="Incident operations console">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">Incident operations</h3>
          <p className="text-[11px] text-slate-500">Append-only ledger · {data.event_count} events · replay {data.replay_equals_materialized_state ? 'verified' : 'failed'}</p>
        </div>
        <div className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400">Live notification delivery disabled</div>
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_280px]">
        <div className="max-h-56 overflow-auto rounded border border-slate-800">
          {data.items.length === 0 ? (
            <div className="p-4 text-xs text-slate-500">No persistent incidents. Bootstrap through the authenticated API when operational materialization is approved.</div>
          ) : data.items.map((item) => (
            <button key={item.incident_id} type="button" onClick={() => setSelected(item.incident_id)} className={`block w-full border-b border-slate-800 p-2 text-left text-xs ${selected === item.incident_id ? 'bg-slate-800' : 'hover:bg-slate-950'}`}>
              <div className="flex justify-between gap-2"><span className="font-mono text-slate-300">{item.incident_id}</span><span className="uppercase text-slate-400">{item.status}</span></div>
              <div className="mt-1 text-[10px] text-slate-500">assignee {item.assignee ?? 'unassigned'} · timeline {item.timeline_count} · escalation {item.escalation_level}</div>
            </button>
          ))}
        </div>
        <div className="space-y-2 rounded border border-slate-800 p-2">
          <input value={actor} onChange={(event) => setActor(event.target.value)} aria-label="Transition actor" className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <input value={reason} onChange={(event) => setReason(event.target.value)} aria-label="Transition reason" className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs" />
          <div className="grid grid-cols-2 gap-1">
            {['acknowledged', 'assigned', 'suppressed', 'resolved', 'reopened', 'threshold_migrated'].map((eventType) => (
              <button key={eventType} type="button" disabled={!selected} onClick={() => transition(eventType)} className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-300 disabled:opacity-40">{eventType}</button>
            ))}
          </div>
          {error && <p role="alert" className="text-[10px] text-red-300">{error}</p>}
        </div>
      </div>
    </section>
  )
}
