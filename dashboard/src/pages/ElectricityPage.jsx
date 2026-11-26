import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { acquireElectricityWorkbook, getElectricityProjection, importElectricityWorkbook, uploadElectricityWorkbook } from '@/lib/electricity-api'
import ElectricityReviews from '@/components/electricity/ElectricityReviews'
import ElectricityJobs from '@/components/electricity/ElectricityJobs'
import ElectricityRegistry from '@/components/electricity/ElectricityRegistry'

const copy = {
  en: {
    title: 'Electricity Intelligence', subtitle: 'Puerto Rico · source evidence workspace',
    scope: 'AUDIT ONLY. Measurements, reconstructions and forecasts remain separate. No authoritative live grid feed is connected. Unavailable data do not mean zero.',
    overview: 'Overview', grid: 'Grid Monitor', registry: 'Plant & generator registry', evidence: 'Evidence inspector', sources: 'Source acquisition',
    loading: 'Loading source evidence…', failure: 'Electricity evidence is unavailable. Check source integrity and backend connectivity.',
    retry: 'Retry', language: 'Language', state: 'Evidence class', metric: 'Metric and unit', since: 'From date',
    unavailable: 'Unavailable — no verified source measurements in this selection.',
    export: 'Export evidence JSON', save: 'Save view', saved: 'View saved on this device.',
    plants: 'Generator claims', artifacts: 'Source receipts', contradictions: 'Unresolved contradictions',
    missing: 'Blocked gates', all: 'All', raw: 'Source SHA-256', time: 'Interval start (UTC)', value: 'Value',
    unit: 'Unit', name: 'Source plant name', capacity: 'Nameplate MW', status: 'Source status',
    authority: 'Authority', retrieved: 'Retrieved at', source: 'Official source',
    url: 'Official EIA workbook URL', acquire: 'Acquire original workbook',
    sourceNote: 'Only original EIA-860M / EIA-923 XLSX or ZIP URLs are accepted. Acquisition preserves bytes; it does not certify the workbook. Operator authentication is required; configure it in System & Tools.',
    digest: 'Captured workbook SHA-256', sheet: 'OOXML worksheet path', date: 'Snapshot effective date',
    file: 'Local original workbook', upload: 'Capture offline workbook', origin: 'Offline origin remains unverified.', attempts: 'Acquisition history',
    import: 'Import EIA-860M claims', busy: 'Working…', result: 'Operation result',
    stages: 'Electricity workspace coverage', blocked: 'Source or implementation gate open',
    links: 'Related native workspaces', outage: 'Outages', hydro: 'Reservoirs & weather', map: 'Infrastructure map', regulatory: 'Regulatory evidence',
  },
  es: {
    title: 'Inteligencia Eléctrica', subtitle: 'Puerto Rico · espacio de evidencia de fuentes',
    scope: 'SOLO AUDITORÍA. Las mediciones, reconstrucciones y pronósticos permanecen separados. No hay una fuente autorizada de telemetría en vivo conectada. Datos no disponibles no significan cero.',
    overview: 'Resumen', grid: 'Monitor de la red', registry: 'Registro de plantas y generadores', evidence: 'Inspector de evidencia', sources: 'Adquisición de fuentes',
    loading: 'Cargando evidencia…', failure: 'La evidencia eléctrica no está disponible. Verifique la integridad de las fuentes y la conexión al servidor.',
    retry: 'Reintentar', language: 'Idioma', state: 'Clase de evidencia', metric: 'Métrica y unidad', since: 'Desde la fecha',
    unavailable: 'No disponible — no hay mediciones verificadas para esta selección.',
    export: 'Exportar evidencia JSON', save: 'Guardar vista', saved: 'Vista guardada en este dispositivo.',
    plants: 'Afirmaciones de generadores', artifacts: 'Recibos de fuentes', contradictions: 'Contradicciones sin resolver',
    missing: 'Criterios bloqueados', all: 'Todas', raw: 'SHA-256 de la fuente', time: 'Inicio del intervalo (UTC)', value: 'Valor',
    unit: 'Unidad', name: 'Nombre de planta en la fuente', capacity: 'MW nominales', status: 'Estado en la fuente',
    authority: 'Autoridad', retrieved: 'Fecha de recuperación', source: 'Fuente oficial',
    url: 'URL del archivo oficial de EIA', acquire: 'Adquirir archivo original',
    sourceNote: 'Se aceptan solo URL originales XLSX o ZIP de EIA-860M / EIA-923. La adquisición conserva los bytes; no certifica el archivo. Se requiere autenticación de operador; configúrela en Sistema y herramientas.',
    digest: 'SHA-256 del archivo adquirido', sheet: 'Ruta de hoja OOXML', date: 'Fecha efectiva de la instantánea',
    file: 'Archivo original local', upload: 'Conservar archivo local', origin: 'El origen del archivo local permanece sin verificar.', attempts: 'Historial de adquisición',
    import: 'Importar afirmaciones EIA-860M', busy: 'Procesando…', result: 'Resultado de la operación',
    stages: 'Cobertura del espacio eléctrico', blocked: 'Criterio de fuente o implementación pendiente',
    links: 'Espacios nativos relacionados', outage: 'Interrupciones', hydro: 'Embalses y clima', map: 'Mapa de infraestructura', regulatory: 'Evidencia regulatoria',
  },
}

const modules = {
  en: ['Hourly grid', 'Generation & fuels', 'Data browser', 'Hydroelectric intelligence', 'GIS', 'Reliability', 'Weather & resilience', 'Forecasts', 'Tariffs', 'PREB orders', 'Capital projects', 'Custom dashboards', 'Notifications', 'Historical replay', 'Reporting', 'Administration'],
  es: ['Red horaria', 'Generación y combustibles', 'Explorador de datos', 'Inteligencia hidroeléctrica', 'SIG', 'Confiabilidad', 'Clima y resiliencia', 'Pronósticos', 'Tarifas', 'Órdenes del NEPR', 'Proyectos de capital', 'Paneles personalizados', 'Notificaciones', 'Reproducción histórica', 'Informes', 'Administración'],
}

function loadView() {
  try {
    const view = JSON.parse(localStorage.getItem('electricity-view-v1') || '{}')
    return view && typeof view === 'object' && !Array.isArray(view) ? view : {}
  } catch { return {} }
}

const inputStyle = 'rounded border border-slate-600 bg-slate-900 p-2 text-slate-100 max-w-full'
const buttonStyle = 'rounded border border-slate-500 px-3 py-2 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-50'

export default function ElectricityPage() {
  const [initial] = useState(loadView)
  const [locale, setLocale] = useState(initial.locale === 'es' ? 'es' : 'en')
  const [tab, setTab] = useState('overview')
  const [kind, setKind] = useState(['OBSERVED', 'RECONSTRUCTED', 'FORECAST', 'SOURCE_CANDIDATE'].includes(initial.kind) ? initial.kind : 'OBSERVED')
  const [series, setSeries] = useState('')
  const [since, setSince] = useState('')
  const [notice, setNotice] = useState('')
  const [url, setUrl] = useState('')
  const [digest, setDigest] = useState('')
  const [sheet, setSheet] = useState('xl/worksheets/sheet1.xml')
  const [date, setDate] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['electricity', 'v1'], queryFn: getElectricityProjection, retry: false, refetchInterval: 60000 })
  const t = copy[locale]
  const data = query.data
  const measurements = data?.states?.[kind]?.measurements || []
  const seriesKeys = [...new Set(measurements.map(m => `${m.entity_id} | ${m.metric} | ${m.unit}`))]
  const selected = seriesKeys.includes(series) ? series : (seriesKeys[0] || '')
  const rows = measurements.filter(m => `${m.entity_id} | ${m.metric} | ${m.unit}` === selected && (!since || m.interval_start.slice(0, 10) >= since)).sort((a, b) => a.interval_start.localeCompare(b.interval_start))

  async function perform(event, operation) {
    event.preventDefault()
    setBusy(true)
    setNotice('')
    try {
      const result = await operation()
      if (result.sha256) setDigest(result.sha256)
      setNotice(JSON.stringify(result))
      await queryClient.invalidateQueries({ queryKey: ['electricity', 'v1'] })
    } catch (error) { setNotice(error.message) } finally { setBusy(false) }
  }

  function saveView() {
    try { localStorage.setItem('electricity-view-v1', JSON.stringify({ locale, kind })); setNotice(t.saved) } catch { setNotice('LOCAL_STORAGE_UNAVAILABLE') }
  }

  function exportEvidence() {
    const href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = href
    link.download = `aguayluz-electricity-${data.revision}.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(href), 1000)
  }

  return <article lang={locale} className="p-4 md:p-6 space-y-5 max-w-7xl mx-auto">
    <header className="flex flex-wrap gap-4 justify-between items-start">
      <div><h1 className="text-2xl font-semibold">{t.title}</h1><p>{t.subtitle}</p></div>
      <label>{t.language} <select className={inputStyle} value={locale} onChange={e => setLocale(e.target.value)}><option value="en">English</option><option value="es">Español</option></select></label>
    </header>
    <p role="note" className="rounded border border-amber-600 bg-amber-950/30 p-3">{t.scope}</p>
    <nav aria-label={t.title} className="flex flex-wrap gap-2">{['overview', 'grid', 'registry', 'evidence', 'sources'].map(key => <button key={key} className={buttonStyle} aria-pressed={tab === key} onClick={() => { setTab(key); setNotice('') }}>{t[key]}</button>)}</nav>
    <div className="flex flex-wrap gap-2">
      <button className={buttonStyle} onClick={saveView}>{t.save}</button>
      <button className={buttonStyle} disabled={!data || query.isError} onClick={exportEvidence}>{t.export}</button>
    </div>
    <output aria-label={t.result} aria-live="polite" className="block break-all">{notice}</output>
    {query.isPending && <p role="status">{t.loading}</p>}
    {query.isError && <div role="alert"><p>{t.failure}</p><button className={buttonStyle} onClick={() => query.refetch()}>{t.retry}</button></div>}
    {data && !query.isError && <>
      <p className="text-sm break-all">{data.certification} · revision {data.revision}</p>
      {tab === 'overview' && <section className="space-y-4">
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3">{[[t.plants, data.generator_claims.length], [t.artifacts, data.sources.length], [t.contradictions, data.contradictions.length]].map(([label, count]) => <div key={label} className="border border-slate-700 rounded p-4"><dt>{label}</dt><dd className="text-2xl">{count}</dd></div>)}</dl>
        <h2 className="text-lg">{t.links}</h2><div className="flex flex-wrap gap-4">{[['/outages', t.outage], ['/hydromet', t.hydro], ['/map', t.map], ['/regulatory', t.regulatory]].map(([to, label]) => <Link key={to} className="text-cyan-300 underline" to={to}>{label}</Link>)}</div>
        <h2 className="text-lg">{t.stages}</h2><ul className="grid sm:grid-cols-2 gap-2">{modules[locale].map(name => <li key={name}>{name}: {t.blocked}</li>)}</ul>
      </section>}
      {tab === 'grid' && <section className="space-y-4">
        <div className="flex flex-wrap gap-3">
          <label>{t.state}<select className={`${inputStyle} block`} value={kind} onChange={e => setKind(e.target.value)}>{Object.keys(data.states).map(s => <option key={s}>{s}</option>)}</select></label>
          <label>{t.metric}<select className={`${inputStyle} block`} value={selected} onChange={e => setSeries(e.target.value)}><option value="">—</option>{seriesKeys.map(s => <option key={s}>{s}</option>)}</select></label>
          <label>{t.since}<input className={`${inputStyle} block`} type="date" value={since} onChange={e => setSince(e.target.value)} /></label>
        </div>
        {!rows.length ? <p role="status" aria-label={t.grid}>{t.unavailable}</p> : <>
          <div aria-label={`${kind} ${selected}`} role="img" className="h-64"><ResponsiveContainer><LineChart data={rows}><XAxis dataKey="interval_start" /><YAxis /><Tooltip /><Line dataKey="value" stroke="#22d3ee" connectNulls={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
          <div className="overflow-x-auto"><table aria-label={t.grid} className="w-full"><thead><tr>{[t.time, t.value, t.unit, t.raw].map(h => <th className="p-2 text-left" key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((m, i) => <tr key={i}><td className="p-2">{m.interval_start} — {m.interval_end}</td><td>{m.value}</td><td>{m.unit}</td><td className="break-all">{m.receipt_sha256}</td></tr>)}</tbody></table></div>
        </>}
      </section>}
      {tab === 'registry' && <ElectricityRegistry key={data.revision} locale={locale} sourceRevision={data.revision} />}
      {tab === 'evidence' && <section className="space-y-3"><h2>{t.missing}</h2><ul>{data.gaps.map(gap => <li key={gap}>{gap}</li>)}</ul><h2>{t.contradictions}</h2><pre className="overflow-auto">{JSON.stringify(data.contradictions, null, 2)}</pre><ElectricityReviews key={data.revision} locale={locale} sourceRevision={data.revision} /></section>}
      {tab === 'sources' && <section className="space-y-5">
        <ElectricityJobs locale={locale} />
        <p>{t.sourceNote}</p>
        <form className="flex flex-wrap items-end gap-3" onSubmit={e => perform(e, () => acquireElectricityWorkbook(url))}>
          <label className="flex-1 min-w-0">{t.url}<input className={`${inputStyle} block w-full`} type="url" required value={url} onChange={e => setUrl(e.target.value)} /></label>
          <button className={buttonStyle} disabled={busy}>{busy ? t.busy : t.acquire}</button>
        </form>
        <form className="flex flex-wrap items-end gap-3" onSubmit={e => perform(e, () => uploadElectricityWorkbook(file, url))}>
          <label>{t.file}<input className={`${inputStyle} block`} type="file" accept=".xlsx,.zip" required onChange={e => setFile(e.target.files[0])} /></label>
          <button className={buttonStyle} disabled={busy || !url || !file}>{busy ? t.busy : t.upload}</button>
          <p>{t.origin}</p>
        </form>
        <form className="flex flex-wrap items-end gap-3" onSubmit={e => perform(e, () => importElectricityWorkbook({ sha256: digest, sheet_path: sheet, effective_at: `${date}T00:00:00Z` }))}>
          <label>{t.digest}<input className={`${inputStyle} block`} required pattern="[0-9a-f]{64}" value={digest} onChange={e => setDigest(e.target.value)} /></label>
          <label>{t.sheet}<input className={`${inputStyle} block`} required value={sheet} onChange={e => setSheet(e.target.value)} /></label>
          <label>{t.date}<input className={`${inputStyle} block`} type="date" required value={date} onChange={e => setDate(e.target.value)} /></label>
          <button className={buttonStyle} disabled={busy}>{busy ? t.busy : t.import}</button>
        </form>
        <div className="overflow-x-auto"><table aria-label={t.artifacts} className="w-full text-sm"><thead><tr>{[t.authority, t.retrieved, t.source, t.raw].map(h => <th className="p-2 text-left" key={h}>{h}</th>)}</tr></thead><tbody>{data.sources.map((s, i) => <tr key={i}><td className="p-2">{s.authority}</td><td>{s.retrieved_at}</td><td><a className="text-cyan-300 underline" href={s.source_url} rel="noreferrer" target="_blank">EIA</a></td><td className="break-all">{s.sha256}</td></tr>)}</tbody></table></div>
        <h2>{t.attempts}</h2><ul>{(data.acquisition_attempts || []).map((attempt, i) => <li key={i}>{attempt.recorded_at} · {attempt.code}</li>)}</ul>
      </section>}
    </>}
  </article>
}
