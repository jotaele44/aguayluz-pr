import { useId, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { cancelElectricityJob, createElectricityJob, getElectricityJobs, stepElectricityJob } from '@/lib/electricity-api'

const copy = {
  en: {
    title: 'Durable monthly acquisition jobs', scope: 'AUDIT ONLY. Each step discovers metadata, verifies PR coverage, or captures one page. Partial results are incomplete research inputs; no measurements are promoted. Operator authentication is required.',
    endpoint: 'EIA route', column: 'Source data column', facet: 'Geography facet', start: 'First source month', end: 'Last source month', page: 'Rows per page', create: 'Create acquisition job',
    refresh: 'Refresh job status', unavailable: 'Job history is unavailable. Controls are disabled until integrity/connectivity is restored.', loading: 'Loading jobs…',
    empty: 'No acquisition jobs recorded.', step: 'Run next step / retry', cancel: 'Cancel job', export: 'Export job evidence', version: 'Version', rows: 'Captured rows', total: 'Source total', unknown: 'Not yet verified',
    lease: 'Lease expires', receipts: 'Checkpoint receipts', history: 'Job history', previous: 'Previous jobs', next: 'Next jobs', jobStatus: 'Current job status',
    failed: 'Operation failed', conflict: 'Job changed or another worker is active. Status was refreshed; inspect it before retrying.',
    states: { QUEUED: 'Queued', RUNNING: 'Running', FAILED: 'Failed', CANCELLED: 'Cancelled', COMPLETE: 'Complete (AUDIT ONLY)' },
    phases: { METADATA: 'Metadata discovery', FACET: 'PR coverage discovery', PAGES: 'Source pages' },
  },
  es: {
    title: 'Trabajos persistentes de adquisición mensual', scope: 'SOLO AUDITORÍA. Cada paso descubre metadatos, verifica cobertura de PR o adquiere una página. Los resultados parciales son insumos de investigación incompletos; no se promueven mediciones. Se requiere autenticación de operador.',
    endpoint: 'Ruta de EIA', column: 'Columna de datos de la fuente', facet: 'Faceta geográfica', start: 'Primer mes de la fuente', end: 'Último mes de la fuente', page: 'Filas por página', create: 'Crear trabajo de adquisición',
    refresh: 'Actualizar estado de trabajos', unavailable: 'El historial de trabajos no está disponible. Los controles están desactivados hasta restaurar la integridad y conexión.', loading: 'Cargando trabajos…',
    empty: 'No hay trabajos de adquisición registrados.', step: 'Ejecutar próximo paso / reintentar', cancel: 'Cancelar trabajo', export: 'Exportar evidencia del trabajo', version: 'Versión', rows: 'Filas adquiridas', total: 'Total de la fuente', unknown: 'Aún sin verificar',
    lease: 'Vencimiento del bloqueo', receipts: 'Recibos de puntos de control', history: 'Historial del trabajo', previous: 'Trabajos anteriores', next: 'Trabajos siguientes', jobStatus: 'Estado actual del trabajo',
    failed: 'La operación falló', conflict: 'El trabajo cambió o hay otro proceso activo. Se actualizó el estado; revíselo antes de reintentar.',
    states: { QUEUED: 'En espera', RUNNING: 'En ejecución', FAILED: 'Fallido', CANCELLED: 'Cancelado', COMPLETE: 'Completo (SOLO AUDITORÍA)' },
    phases: { METADATA: 'Descubrimiento de metadatos', FACET: 'Descubrimiento de cobertura de PR', PAGES: 'Páginas de la fuente' },
  },
}
const style = 'border border-slate-600 rounded bg-slate-950 p-2 max-w-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-50'
const newId = () => crypto.randomUUID().replaceAll('-', '')

export default function ElectricityJobs({ locale }) {
  const queryClient = useQueryClient()
  const id = useId()
  const t = copy[locale]
  const [offset, setOffset] = useState(0)
  const [fields, setFields] = useState({ endpoint: 'facility-fuel', data_column: 'generation', state_facet: 'state', start: '', end: '', page_size: 1000 })
  const [requestId, setRequestId] = useState(newId)
  const [pending, setPending] = useState({})
  const [notice, setNotice] = useState('')
  const query = useQuery({ queryKey: ['electricity-jobs', offset], queryFn: () => getElectricityJobs(offset), retry: false, refetchInterval: 2000 })
  const data = query.data
  function change(key, value) { setFields(v => ({ ...v, [key]: value })); setRequestId(newId()); setNotice('') }
  async function perform(key, operation) {
    setPending(v => ({ ...v, [key]: true })); setNotice('')
    try {
      const result = await operation()
      setNotice(`${result.job_id}: ${t.states[result.status]}${result.error ? ` · ${result.error}` : ''}`)
      if (key === 'create') setRequestId(newId())
      await query.refetch()
    } catch (error) {
      setNotice(error.message === 'ELECTRICITY_HTTP_409' ? t.conflict : `${t.failed}: ${error.message}`)
      await query.refetch()
    } finally {
      // Even a failed/fenced step may have preserved new raw evidence.
      await queryClient.invalidateQueries({ queryKey: ['electricity', 'v1'] })
      setPending(v => ({ ...v, [key]: false }))
    }
  }
  function download(job) {
    const href = URL.createObjectURL(new Blob([JSON.stringify(job, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = href; link.download = `aguayluz-acquisition-${job.job_id}-v${job.version}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(href), 1000)
  }
  const disabled = query.isError || !data
  return <section aria-label={t.title} className="space-y-3 min-w-0">
    <h2>{t.title}</h2><p>{t.scope}</p>
    {query.isPending && <p role="status">{t.loading}</p>}
    {query.isError && <p role="alert">{t.unavailable}</p>}
    <button className={style} disabled={query.isFetching} onClick={() => query.refetch()}>{t.refresh}</button>
    <form className="flex flex-wrap gap-3 items-end" onSubmit={e => { e.preventDefault(); perform('create', () => createElectricityJob({ ...fields, request_id: requestId })) }}>
      <div><label htmlFor={`${id}-endpoint`}>{t.endpoint}</label><select id={`${id}-endpoint`} className={`${style} block`} value={fields.endpoint} onChange={e => change('endpoint', e.target.value)}><option>facility-fuel</option><option>retail-sales</option></select></div>
      <div><label htmlFor={`${id}-column`}>{t.column}</label><input id={`${id}-column`} className={`${style} block`} required pattern={'[A-Za-z][A-Za-z0-9_\\-]{0,63}'} value={fields.data_column} onChange={e => change('data_column', e.target.value)} /></div>
      <div><label htmlFor={`${id}-facet`}>{t.facet}</label><select id={`${id}-facet`} className={`${style} block`} value={fields.state_facet} onChange={e => change('state_facet', e.target.value)}>{['state', 'stateid', 'plantState'].map(f => <option key={f}>{f}</option>)}</select></div>
      {['start', 'end', 'page_size'].map(key => <div key={key}><label htmlFor={`${id}-${key}`}>{t[{ start: 'start', end: 'end', page_size: 'page' }[key]]}</label><input id={`${id}-${key}`} className={`${style} block`} type={key === 'page_size' ? 'number' : 'month'} min={key === 'page_size' ? 1 : undefined} max={key === 'page_size' ? 5000 : undefined} required value={fields[key]} onChange={e => change(key, key === 'page_size' ? Number(e.target.value) : e.target.value)} /></div>)}
      <button className={style} disabled={disabled || pending.create}>{t.create}</button>
    </form>
    <output aria-live="polite" className="block break-all">{notice}</output>
    {data && !query.isError && <>
      {!data.jobs.length && <p>{t.empty}</p>}
      {data.jobs.map(job => <section key={job.job_id} aria-label={job.job_id} className="border border-slate-700 rounded p-3 space-y-3 min-w-0">
        <h3 className="break-all">{job.job_id}</h3><p role="status" aria-label={t.jobStatus}>{t.states[job.status]} · {t.phases[job.phase]} · {t.version} {job.version}</p>
        <p>{job.spec.endpoint} / {job.spec.data_column} / PR · {job.spec.start} — {job.spec.end}</p>
        <p>{t.rows}: {job.rows} · {t.total}: {job.total ?? t.unknown}</p>
        {job.lease_expires_at && <p>{t.lease}: {job.lease_expires_at}</p>}
        {job.error && <p role="status">{t.states.FAILED}: {job.error}</p>}
        <div className="flex flex-wrap gap-2">
          <button className={style} disabled={!job.can_step || pending[`step:${job.job_id}`]} onClick={() => perform(`step:${job.job_id}`, () => stepElectricityJob(job.job_id, job.version))}>{t.step}</button>
          <button className={style} disabled={!job.can_cancel || pending[`cancel:${job.job_id}`]} onClick={() => perform(`cancel:${job.job_id}`, () => cancelElectricityJob(job.job_id, job.version))}>{t.cancel}</button>
          <button className={style} onClick={() => download(job)}>{t.export}</button>
        </div>
        <details><summary>{t.receipts} ({job.receipt_sha256.length})</summary><ul>{job.receipt_sha256.map((digest, i) => <li key={i} className="break-all">{digest}</li>)}</ul></details>
        <details><summary>{t.history}</summary><ul>{job.history.map(event => <li key={event.version}>{event.updated_at} · {event.version} · {t.states[event.status]} · {t.phases[event.phase]} · {event.rows}{event.error && ` · ${event.error}`}</li>)}</ul></details>
      </section>)}
      <p>{offset + data.jobs.length} / {data.total}</p><div className="flex gap-2"><button className={style} disabled={!offset} onClick={() => setOffset(v => Math.max(0, v - 20))}>{t.previous}</button><button className={style} disabled={data.next_offset === null} onClick={() => setOffset(data.next_offset)}>{t.next}</button></div>
    </>}
  </section>
}
