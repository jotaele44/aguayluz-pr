export function toCSV(rows, columns) {
  if (!rows.length) return ''
  const cols = columns || Object.keys(rows[0])
  const escape = (v) => {
    const s = `${v ?? ''}`
    return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
  }
  const header = cols.join(',')
  const body = rows.map((r) => cols.map((c) => escape(r[c])).join(',')).join('\n')
  return `${header}\n${body}`
}

export function downloadCSV(filename, rows, columns) {
  const csv = toCSV(rows, columns)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
