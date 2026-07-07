import { useMemo } from 'react'
import { useAssets, useEvents } from '@/lib/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  PieChart, Pie, Cell,
} from 'recharts'

const TIP = { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, fontSize: 11, color: '#cbd5e1' }
const COLORS = ['#38bdf8', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#fb923c', '#e879f9']

export default function AnalyticsPage() {
  const { data: assets = [], isLoading: aLoad } = useAssets()
  const { data: events = [], isLoading: eLoad } = useEvents()
  const isLoading = aLoad || eLoad

  const eventsByType = useMemo(() => {
    const counts = {}
    for (const e of events) {
      const t = e.event_type || 'other'
      counts[t] = (counts[t] || 0) + 1
    }
    return Object.entries(counts).map(([name, value]) => ({ name: name.replace(/_/g, ' '), value }))
      .sort((a, b) => b.value - a.value)
  }, [events])

  const eventsByMunicipality = useMemo(() => {
    const counts = {}
    for (const e of events) {
      const m = e.municipality || 'Unknown'
      counts[m] = (counts[m] || 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 15)
      .map(([name, value]) => ({ name, value }))
  }, [events])

  const assetsByType = useMemo(() => {
    const counts = {}
    for (const a of assets) {
      const t = a.asset_type || 'other'
      counts[t] = (counts[t] || 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12)
      .map(([name, value]) => ({ name, value }))
  }, [assets])

  const assetsByStatus = useMemo(() => {
    const counts = {}
    for (const a of assets) {
      const s = a.status || 'unknown'
      counts[s] = (counts[s] || 0) + 1
    }
    return Object.entries(counts).map(([name, value]) => ({ name, value }))
  }, [assets])

  if (isLoading) {
    return (
      <div className="p-6 grid grid-cols-2 gap-6">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-80 rounded-lg" />)}
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-[1400px]">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">Analytics</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          {assets.length.toLocaleString()} assets · {events.length.toLocaleString()} events
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Chart title="Events by Type">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={eventsByType} layout="vertical" margin={{ top: 4, right: 12, left: 90, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
              <XAxis type="number" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} width={90} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={TIP} />
              <Bar dataKey="value" fill="#38bdf8" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Chart>

        <Chart title="Top Municipios by Event Count">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={eventsByMunicipality} layout="vertical" margin={{ top: 4, right: 12, left: 90, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
              <XAxis type="number" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} width={90} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={TIP} />
              <Bar dataKey="value" fill="#a78bfa" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Chart>

        <Chart title="Assets by Type (top 12)">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={assetsByType} layout="vertical" margin={{ top: 4, right: 12, left: 110, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
              <XAxis type="number" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} width={110} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={TIP} />
              <Bar dataKey="value" fill="#34d399" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Chart>

        <Chart title="Asset Status Distribution">
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={assetsByStatus}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={80}
                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                labelLine={false}
                fontSize={10}
              >
                {assetsByStatus.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={TIP} />
            </PieChart>
          </ResponsiveContainer>
        </Chart>
      </div>
    </div>
  )
}

function Chart({ title, children }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4">{title}</h3>
      {children}
    </div>
  )
}
