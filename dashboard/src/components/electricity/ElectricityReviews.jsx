import { useId, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { appendElectricityReview, getElectricityReviews } from '@/lib/electricity-api'

const text = {
  en: {
    title: 'Candidate review recommendations',
    scope: 'Recommendations preserve every source claim and contradiction. They do not certify, promote, exclude or alter scientific evidence. Authentication records a shared operator role, not an individual identity.',
    loading: 'Loading review history…', unavailable: 'Review history is unavailable. Writes and review export are disabled until integrity is restored.',
    empty: 'No captured generator claims are available for review.', retry: 'Refresh review history',
    claim: 'Exact generator claim', action: 'Recommendation', reason: 'Reason', submit: 'Record recommendation',
    busy: 'Recording…', saved: 'Recommendation recorded.', failed: 'Recommendation failed.',
    conflict: 'The source or review history changed, or the request conflicts. History was refreshed; inspect it before submitting again.',
    export: 'Export review history JSON', history: 'Immutable review history', time: 'Recorded at (UTC)',
    actor: 'Authenticated role', event: 'Event SHA-256', active: 'Current recommendation', none: 'No active recommendation',
    actions: { RECOMMEND_RETAIN: 'Recommend retaining candidate', RECOMMEND_EXCLUDE: 'Recommend excluding candidate', DEFER: 'Defer pending evidence', REVERSE: 'Reverse current recommendation' },
    reasons: { ORIGINAL_REQUIRED: 'Original source required', CAPACITY_CONFLICT: 'Capacity conflict', STATUS_CONFLICT: 'Status conflict', TEMPORAL_CONFLICT: 'Temporal conflict', SOURCE_DISAGREEMENT: 'Sources disagree', REVIEW_CORRECTION: 'Review correction' },
  },
  es: {
    title: 'Recomendaciones de revisión de candidatos',
    scope: 'Las recomendaciones conservan toda afirmación y contradicción de las fuentes. No certifican, promueven, excluyen ni alteran la evidencia científica. La autenticación registra un rol de operador compartido, no una identidad individual.',
    loading: 'Cargando historial de revisión…', unavailable: 'El historial de revisión no está disponible. La escritura y exportación permanecen desactivadas hasta restaurar la integridad.',
    empty: 'No hay afirmaciones de generadores adquiridas para revisar.', retry: 'Actualizar historial de revisión',
    claim: 'Afirmación exacta del generador', action: 'Recomendación', reason: 'Motivo', submit: 'Registrar recomendación',
    busy: 'Registrando…', saved: 'Recomendación registrada.', failed: 'La recomendación falló.',
    conflict: 'La fuente o el historial cambió, o la solicitud tiene un conflicto. Se actualizó el historial; revíselo antes de volver a enviar.',
    export: 'Exportar historial de revisión JSON', history: 'Historial inmutable de revisión', time: 'Fecha de registro (UTC)',
    actor: 'Rol autenticado', event: 'SHA-256 del evento', active: 'Recomendación actual', none: 'Sin recomendación activa',
    actions: { RECOMMEND_RETAIN: 'Recomendar conservar candidato', RECOMMEND_EXCLUDE: 'Recomendar excluir candidato', DEFER: 'Aplazar hasta obtener evidencia', REVERSE: 'Revertir recomendación actual' },
    reasons: { ORIGINAL_REQUIRED: 'Se requiere fuente original', CAPACITY_CONFLICT: 'Conflicto de capacidad', STATUS_CONFLICT: 'Conflicto de estado', TEMPORAL_CONFLICT: 'Conflicto temporal', SOURCE_DISAGREEMENT: 'Las fuentes discrepan', REVIEW_CORRECTION: 'Corrección de revisión' },
  },
}

const control = 'border border-slate-600 rounded bg-slate-950 p-2 max-w-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-50'

export default function ElectricityReviews({ locale, sourceRevision }) {
  const controlId = useId()
  const t = text[locale]
  const query = useQuery({ queryKey: ['electricity-reviews', sourceRevision], queryFn: getElectricityReviews, retry: false })
  const client = useQueryClient()
  const [selected, setSelected] = useState('')
  const [action, setAction] = useState('DEFER')
  const [reason, setReason] = useState('ORIGINAL_REQUIRED')
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(null)
  const [notice, setNotice] = useState('')
  const data = query.data
  const target = data?.claims.find(c => c.claim_id === selected) || data?.claims[0]
  const coherent = data?.source_revision === sourceRevision
  const disabled = busy || query.isError || !coherent || !target || (action === 'REVERSE' && !target.active_recommendation)

  function change(setter, value) { setter(value); setPending(null); setNotice('') }

  async function record(event) {
    event.preventDefault()
    if (disabled) return
    const body = pending || {
      request_id: crypto.randomUUID().replaceAll('-', ''), source_revision: sourceRevision,
      expected_review_revision: data.revision, claim_id: target.claim_id,
      action, reason_code: reason, reverses: action === 'REVERSE' ? target.active_recommendation : null,
    }
    setPending(body)
    setBusy(true)
    setNotice('')
    try {
      const result = await appendElectricityReview(body)
      setPending(null)
      setNotice(`${t.saved} ${result.event.event_id}`)
      await client.invalidateQueries({ queryKey: ['electricity-reviews'] })
    } catch (error) {
      if (error.message === 'ELECTRICITY_HTTP_409') {
        setPending(null)
        setNotice(t.conflict)
        await query.refetch()
      } else setNotice(`${t.failed} ${error.message}`)
    } finally { setBusy(false) }
  }

  function exportHistory() {
    const href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = href
    link.download = `aguayluz-electricity-reviews-${data.revision}.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(href), 1000)
  }

  return <section aria-label={t.title} className="space-y-3 min-w-0">
    <h2>{t.title}</h2><p>{t.scope}</p>
    {query.isPending && <p role="status">{t.loading}</p>}
    {query.isError && <p role="alert">{t.unavailable}</p>}
    <div className="flex flex-wrap gap-2">
      <button className={control} disabled={busy || query.isFetching} onClick={() => { setPending(null); query.refetch() }}>{t.retry}</button>
      <button className={control} disabled={!data || query.isError || !coherent} onClick={exportHistory}>{t.export}</button>
    </div>
    {data && !query.isError && <>
      {!coherent && <p role="alert">{t.conflict}</p>}
      {!data.claims.length && <p>{t.empty}</p>}
      <form onSubmit={record} className="space-y-3 min-w-0">
        <div><label htmlFor={`${controlId}-claim`}>{t.claim}</label><select id={`${controlId}-claim`} className={`${control} block w-full min-w-0`} value={target?.claim_id || ''} disabled={busy || !data.claims.length} onChange={e => change(setSelected, e.target.value)}>
          {!data.claims.length && <option value="">—</option>}
          {data.claims.map(c => <option key={c.claim_id} value={c.claim_id}>{c.source_identity} · {c.claim_id}</option>)}
        </select></div>
        <p className="break-all">{t.active}: {target?.active_action ? t.actions[target.active_action] : t.none}</p>
        <div className="flex flex-wrap gap-3">
          <div><label htmlFor={`${controlId}-action`}>{t.action}</label><select id={`${controlId}-action`} className={`${control} block`} value={action} disabled={busy} onChange={e => change(setAction, e.target.value)}>{Object.entries(t.actions).map(([code, label]) => <option key={code} value={code} disabled={code === 'REVERSE' && !target?.active_recommendation}>{label}</option>)}</select></div>
          <div><label htmlFor={`${controlId}-reason`}>{t.reason}</label><select id={`${controlId}-reason`} className={`${control} block`} value={reason} disabled={busy} onChange={e => change(setReason, e.target.value)}>{Object.entries(t.reasons).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></div>
          <button className={control} disabled={disabled}>{busy ? t.busy : t.submit}</button>
        </div>
      </form>
      <h3>{t.history}</h3>
      <div className="overflow-x-auto"><table aria-label={t.history} className="w-full text-sm"><thead><tr>{[t.time, t.action, t.reason, t.actor, t.event].map(label => <th key={label} className="p-2 text-left">{label}</th>)}</tr></thead><tbody>{data.events.map(event => <tr key={event.event_id}><td className="p-2">{event.recorded_at}</td><td>{t.actions[event.action]}</td><td>{t.reasons[event.reason_code]}</td><td>{event.actor}</td><td className="break-all">{event.event_id}{event.reverses && <span className="block">↩ {event.reverses}</span>}</td></tr>)}</tbody></table></div>
    </>}
    <output aria-live="polite" className="block break-all">{notice}</output>
  </section>
}
