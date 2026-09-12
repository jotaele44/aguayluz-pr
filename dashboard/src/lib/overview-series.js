// Preserve site identity and units. Invalid or tied timestamps are excluded
// from the chart, not silently converted to zero or merged into synthetic rows.
function observedTime(row) {
  const value = row.observed_date ?? row.timestamp ?? row.date
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?$/.test(value)) return NaN
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== value.slice(0, 10)) return NaN
  return Date.parse(value)
}

export function reservoirStorageSeries(rows, site) {
  if (typeof site !== 'string' || !site.length) return { points: [], excluded: rows.length }
  const selected = rows.filter((row) => row?.site_no === site)
  const valid = selected.filter((row) => row.metric === 'reservoir_storage_pct'
    && row.unit === '%' && typeof row.value === 'number' && Number.isFinite(row.value)
    && row.value >= 0 && row.value <= 100
    && Number.isFinite(observedTime(row)))
  const times = new Map()
  for (const row of valid) {
    const time = observedTime(row)
    times.set(time, (times.get(time) ?? 0) + 1)
  }
  const retained = valid.filter((row) => times.get(observedTime(row)) === 1)
    .sort((a, b) => observedTime(a) - observedTime(b))
  return {
    points: retained.slice(-30).map((row) => ({ t: row.observed_date ?? row.timestamp ?? row.date, v: row.value })),
    excluded: selected.length - retained.length,
  }
}
