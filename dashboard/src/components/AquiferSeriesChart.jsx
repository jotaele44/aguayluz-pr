import { useMemo } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Database } from 'lucide-react'
import { CHART_TOOLTIP_STYLE } from '@/lib/format'
import { useAquiferSeries } from '@/lib/hydro-inventory-hooks'

const axis = { fill: '#94a3b8', fontSize: 11 }

// Median of each contributing well's monthly departure from its own normal. Display only.
export default function AquiferSeriesChart({ aquifer, aquiferName, includePolygon }) {
  const query = useAquiferSeries(aquifer, includePolygon)
  const data = query.data
  const chart = useMemo(() => (data?.points ?? []).map((p) => ({ ...p, value: p.median_ft })), [data])
  const changes = chart.filter((p) => p.membership_changed)
  const latest = [...chart].reverse().find((p) => p.value != null)
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3" data-testid="aquifer-series">
      <div className="text-xs uppercase tracking-wide text-slate-400">Aquifer depth anomaly (median of wells) · {aquiferName}</div>
      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{data?.limits ?? 'Median of each well\'s departure from its own normal for that month. Not a water-table elevation or a storage estimate.'}</p>
      {data && (
        <p className="mt-1 text-[11px] text-slate-500">
          {data.members.length} wells in scope · {data.contributing_wells.length} with a five-year baseline · {data.points_with_value ?? 0} months with three or more wells
          {includePolygon ? ` · ${data.excluded_wells?.coded_to_another_aquifer ?? 0} wells inside the outline left out because USGS assigns them to another aquifer` : ''}
          {latest ? ` · latest ${latest.month}: ${latest.value > 0 ? '+' : ''}${latest.value} ft (n=${latest.n})` : ''}
        </p>
      )}
      <div className="mt-2 h-52">
        {query.isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">Loading aquifer series…</div>
        ) : query.isError ? (
          <div className="flex h-full items-center justify-center text-sm text-red-300">Aquifer series unavailable: {String(query.error?.message ?? query.error)}</div>
        ) : !chart.some((p) => p.value != null) ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 rounded border border-dashed border-slate-800 text-center text-sm text-slate-500">
            <Database className="h-5 w-5 text-slate-600" />
            {data?.readings_present === false
              ? 'This server holds no reading files, so no aquifer series can be computed here.'
              : 'Not enough wells with a five-year record in any month (three are needed).'}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chart} margin={{ top: 4, right: 8, bottom: 4, left: -12 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="month" tick={axis} />
              <YAxis tick={axis} reversed unit=" ft" />
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE} formatter={(v, _n, item) => [v == null ? 'fewer than 3 wells' : `${v} ft (n=${item.payload.n})`, 'median anomaly']} />
              <ReferenceLine y={0} stroke="#475569" />
              {changes.map((p) => <ReferenceLine key={p.month} x={p.month} stroke="#a855f7" strokeDasharray="2 3" />)}
              <Line type="monotone" dataKey="value" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      {changes.length > 0 && <p className="mt-1 text-[10px] text-purple-300">Dashed purple lines: the set of contributing wells changed that month.</p>}
      <p className="mt-1 text-[10px] text-slate-600">Axis reversed: up means shallower water than usual. {data?.provisional_points?.length ? `${data.provisional_points.length} provisional months are kept out of this line.` : ''}</p>
    </div>
  )
}
