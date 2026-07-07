import { useState, useEffect, useRef } from 'react'
import { API_BASE } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { Zap, Play, Pause } from 'lucide-react'
import { fmtDate } from '@/lib/format'

const TYPE_TONE = {
  outage: 'bg-red-950/60 text-red-300 border-red-900',
  service_interruption: 'bg-amber-950/60 text-amber-300 border-amber-900',
  restoration: 'bg-emerald-950/60 text-emerald-300 border-emerald-900',
  boil_water: 'bg-sky-950/60 text-sky-300 border-sky-900',
  project_update: 'bg-violet-950/60 text-violet-300 border-violet-900',
}
const EVENT_TYPES = ['all', 'outage', 'service_interruption', 'restoration', 'boil_water', 'project_update']

export default function LiveLogsPage() {
  const [events, setEvents] = useState([])
  const [type, setType] = useState('all')
  const [q, setQ] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [connected, setConnected] = useState(false)
  const listRef = useRef(null)

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/events/stream`)
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = (evt) => {
      try { setEvents(JSON.parse(evt.data)) } catch {}
    }
    return () => es.close()
  }, [])

  useEffect(() => {
    if (autoScroll && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [events, autoScroll])

  const filtered = events.filter((e) =>
    (type === 'all' || e.event_type === type) &&
    (!q || (e.affected_area || '').toLowerCase().includes(q.toLowerCase()) ||
           (e.municipality || '').toLowerCase().includes(q.toLowerCase()))
  )

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-6 py-4 border-b border-slate-800 flex-wrap shrink-0">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Live Logs</h1>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={cn('w-1.5 h-1.5 rounded-full', connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400')} />
            <span className="text-xs text-slate-500">{connected ? 'SSE connected · refreshes every 5 s' : 'Disconnected'}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter area / municipio…" className="h-7 w-44 text-xs bg-slate-950 border-slate-800" />
          <Select value={type} onValueChange={setType}>
            <SelectTrigger className="h-7 w-[150px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{EVENT_TYPES.map((t) => <SelectItem key={t} value={t} className="text-xs capitalize">{t.replace(/_/g, ' ')}</SelectItem>)}</SelectContent>
          </Select>
          <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={() => setAutoScroll(s => !s)}>
            {autoScroll ? <Pause className="h-3.5 w-3.5 mr-1" /> : <Play className="h-3.5 w-3.5 mr-1" />}
            {autoScroll ? 'Pause' : 'Resume'}
          </Button>
        </div>
      </div>
      <div ref={listRef} className="flex-1 overflow-auto p-4 space-y-1 font-mono text-xs">
        {filtered.map((e, i) => (
          <div key={e.event_id ?? i} className={cn(
            'flex items-center gap-3 rounded border px-3 py-2',
            TYPE_TONE[e.event_type] ?? 'bg-slate-900 border-slate-800 text-slate-400',
          )}>
            <Zap className="h-3 w-3 shrink-0 opacity-70" />
            <span className="shrink-0 text-[10px] opacity-50 w-24">{fmtDate(e.start_time)}</span>
            <span className="capitalize opacity-80 shrink-0 w-28">{(e.event_type || '').replace(/_/g, ' ')}</span>
            <span className="truncate">{e.affected_area}{e.municipality ? ` · ${e.municipality}` : ''}</span>
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-center text-slate-500 py-16">
            {connected ? 'Stream connected — no events yet' : 'Connecting to event stream…'}
          </p>
        )}
      </div>
    </div>
  )
}
