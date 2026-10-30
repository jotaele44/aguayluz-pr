import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getElectricityRegistry, getElectricityRegistryHistory } from '@/lib/electricity-api'

const text = {
  en: {
    title: 'Temporal source registry', tableScroll: 'Registry table scroll area', historyScroll: 'History table scroll area', note: 'SOURCE_CANDIDATE · AUDIT ONLY. Plant entries are references from generator source IDs. Separate source systems are not crosswalks. Effective dates describe source assertions, not operating state. Open intervals stay open; no winning claim or available capacity is inferred.',
    kind: 'Entity type', generator: 'Generators', plant: 'Plant references', source: 'Source system', all: 'All source systems', plantId: 'Exact plant ID', search: 'Literal name or ID contains', at: 'Effective instant (UTC)', apply: 'Apply registry filters', clear: 'Clear registry filters',
    loading: 'Loading registry…', error: 'Registry evidence is unavailable or its revision changed. Refresh to verify the source snapshot.', retry: 'Refresh registry evidence', empty: 'Unavailable — no source assertions match this selection. This is not zero generation.',
    count: 'Matching source identities', identifier: 'Source identifiers', name: 'Source plant names', versions: 'Selected / history claims', conflicts: 'Conflicting selected pairs', inspect: 'Inspect history', previous: 'Previous identities', next: 'Next identities',
    history: 'Source assertion history', close: 'Close history', time: 'Source validity [start, end)', open: 'Open end', selected: 'Selected at instant', yes: 'Yes', no: 'No', status: 'Source status', capacity: 'Nameplate MW', hash: 'Source SHA-256', claim: 'Claim ID', contradiction: 'Overlapping conflicting claim IDs', none: 'None',
    disclosures: 'Source disclosures for this history page', license: 'License', published: 'Published at', retrieved: 'Retrieved at', unknown: 'Unresolved', authority: 'Authority', sourceLink: 'Source URL',
    historyPrev: 'Previous history page', historyNext: 'Next history page', export: 'Export this registry page', exportHistory: 'Export this history page', bounds: 'Exports contain this bounded page and its source revision; history pages retain all assertions, including those outside the selected instant.',
  },
  es: {
    title: 'Registro temporal de fuentes', tableScroll: 'Área desplazable del registro', historyScroll: 'Área desplazable del historial', note: 'SOURCE_CANDIDATE · SOLO AUDITORÍA. Las plantas son referencias de identificadores de generadores. Las fuentes separadas no son equivalencias verificadas. Las fechas describen afirmaciones de la fuente, no el estado operativo. Los intervalos abiertos permanecen abiertos; no se infiere una afirmación ganadora ni capacidad disponible.',
    kind: 'Tipo de entidad', generator: 'Generadores', plant: 'Referencias de plantas', source: 'Sistema de origen', all: 'Todos los sistemas', plantId: 'ID exacto de planta', search: 'Nombre o ID literal contiene', at: 'Instante efectivo (UTC)', apply: 'Aplicar filtros del registro', clear: 'Restablecer filtros del registro',
    loading: 'Cargando registro…', error: 'La evidencia del registro no está disponible o cambió su revisión. Actualice para verificar la instantánea.', retry: 'Actualizar evidencia del registro', empty: 'No disponible — ninguna afirmación coincide con la selección. Esto no significa generación cero.',
    count: 'Identidades de origen coincidentes', identifier: 'Identificadores de origen', name: 'Nombres de planta en la fuente', versions: 'Afirmaciones seleccionadas / históricas', conflicts: 'Pares seleccionados en conflicto', inspect: 'Inspeccionar historial', previous: 'Identidades anteriores', next: 'Identidades siguientes',
    history: 'Historial de afirmaciones de la fuente', close: 'Cerrar historial', time: 'Vigencia de fuente [inicio, fin)', open: 'Sin fecha de cierre', selected: 'Seleccionada en el instante', yes: 'Sí', no: 'No', status: 'Estado en la fuente', capacity: 'MW nominales', hash: 'SHA-256 de la fuente', claim: 'ID de afirmación', contradiction: 'ID de afirmaciones superpuestas en conflicto', none: 'Ninguno',
    disclosures: 'Información de fuentes en esta página de historial', license: 'Licencia', published: 'Fecha de publicación', retrieved: 'Fecha de recuperación', unknown: 'Sin resolver', authority: 'Autoridad', sourceLink: 'URL de origen',
    historyPrev: 'Página anterior del historial', historyNext: 'Página siguiente del historial', export: 'Exportar esta página del registro', exportHistory: 'Exportar esta página del historial', bounds: 'Las exportaciones contienen esta página limitada y su revisión de origen; el historial conserva todas las afirmaciones, incluso fuera del instante seleccionado.',
  },
}
const initial = { entity_kind: 'generator', source_system: '', plant_id: '', search: '', at: '' }
const inputStyle = 'rounded border border-slate-500 bg-slate-900 p-2 block w-full text-slate-100'
const buttonStyle = 'rounded border border-slate-500 px-3 py-2 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-50'

function parameters(filters) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== '').map(([key, value]) => [key, key === 'at' ? `${value}Z` : value]))
}
function download(value, name) {
  const href = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = href; link.download = name; link.click()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}

export default function ElectricityRegistry({ locale = 'en', sourceRevision }) {
  const t = text[locale]
  const [draft, setDraft] = useState(initial)
  const [filters, setFilters] = useState(initial)
  const [offset, setOffset] = useState(0)
  const [entityId, setEntityId] = useState(null)
  const [historyOffset, setHistoryOffset] = useState(0)
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['electricity', 'registry', sourceRevision, filters, offset],
    queryFn: () => getElectricityRegistry({ ...parameters(filters), offset, limit: 20, revision: sourceRevision }), retry: false })
  const data = query.data
  const history = useQuery({ queryKey: ['electricity', 'registry-history', sourceRevision, entityId, filters.at, historyOffset],
    queryFn: () => getElectricityRegistryHistory(entityId, { ...parameters({ at: filters.at }), offset: historyOffset, limit: 20, revision: sourceRevision }), enabled: !!entityId && !!data && !query.isError, retry: false })
  const detail = history.data
  function apply(event, values = draft) {
    event.preventDefault()
    setFilters(values); setOffset(0); setEntityId(null); setHistoryOffset(0)
  }
  async function refresh() {
    await client.invalidateQueries({ queryKey: ['electricity', 'v1'] })
    await query.refetch()
    if (entityId) await history.refetch()
  }
  function field(key, type = 'text') {
    return <label>{t[key === 'plant_id' ? 'plantId' : key]}<input className={inputStyle} type={type} step={type === 'datetime-local' ? '1' : undefined} maxLength={key === 'search' ? 100 : undefined} pattern={key === 'plant_id' ? '[1-9][0-9]*' : undefined} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>
  }
  return <section aria-label={t.title} className="space-y-4 min-w-0">
    <h2 className="text-xl">{t.title}</h2><p role="note">{t.note}</p>
    <form onSubmit={apply} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <label>{t.kind}<select aria-label={t.kind} className={inputStyle} value={draft.entity_kind} onChange={e => setDraft({ ...draft, entity_kind: e.target.value })}><option value="generator">{t.generator}</option><option value="plant">{t.plant}</option></select></label>
      <label>{t.source}<select aria-label={t.source} className={inputStyle} value={draft.source_system} onChange={e => setDraft({ ...draft, source_system: e.target.value })}><option value="">{t.all}</option>{['EIA-860M', 'EIA-860', 'EIA-923'].map(s => <option key={s}>{s}</option>)}</select></label>
      {field('plant_id')}{field('search')}{field('at', 'datetime-local')}
      <div className="flex flex-wrap gap-2 items-end"><button className={buttonStyle}>{t.apply}</button><button className={buttonStyle} type="button" onClick={e => { setDraft(initial); apply(e, initial) }}>{t.clear}</button></div>
    </form>
    <button className={buttonStyle} onClick={refresh}>{t.retry}</button>
    <p>{t.bounds}</p>
    {query.isPending && <p role="status">{t.loading}</p>}
    {query.isError && <p role="alert">{t.error}</p>}
    {data && !query.isError && <>
      <p className="break-all">{data.certification} · {data.source_revision}</p>
      <p role="status" aria-label={t.count}>{t.count}: {data.total}</p>
      <button className={buttonStyle} onClick={() => download(data, `electricity-registry-${data.source_revision}-${offset}.json`)}>{t.export}</button>
      {!data.entities.length ? <p role="status">{t.empty}</p> : <div role="region" aria-label={t.tableScroll} tabIndex={0} className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300"><table aria-label={t.title} className="w-full text-sm"><thead><tr>{[t.identifier, t.name, t.versions, t.conflicts, t.inspect].map(h => <th scope="col" className="p-2 text-left" key={h}>{h}</th>)}</tr></thead><tbody>{data.entities.map(e => <tr key={e.entity_id}>
        <td className="p-2">{e.source_system} · {e.plant_id}{e.generator_id !== null && ` / ${e.generator_id}`}<span className="block break-all">{e.identity_basis}</span></td><td className="p-2">{e.names.join(' · ')}</td><td className="p-2">{e.selected_claim_count} / {e.history_claim_count}</td><td className="p-2">{e.conflicting_pair_count}</td>
        <td className="p-2"><button className={buttonStyle} aria-label={`${t.inspect}: ${e.source_system} ${e.plant_id}${e.generator_id !== null ? ` / ${e.generator_id}` : ''}`} onClick={() => { setEntityId(e.entity_id); setHistoryOffset(0) }}>{t.inspect}</button></td>
      </tr>)}</tbody></table></div>}
      <div className="flex flex-wrap gap-2"><button className={buttonStyle} disabled={!offset} onClick={() => { setOffset(Math.max(0, offset - 20)); setEntityId(null) }}>{t.previous}</button><button className={buttonStyle} disabled={data.next_offset === null} onClick={() => { setOffset(data.next_offset); setEntityId(null) }}>{t.next}</button></div>
      {entityId && <section aria-label={t.history} className="space-y-3 min-w-0">
        <h3 className="text-lg">{t.history}</h3><button className={buttonStyle} onClick={() => setEntityId(null)}>{t.close}</button>
        {history.isPending && <p role="status">{t.loading}</p>}{history.isError && <p role="alert">{t.error}</p>}
        {detail && !history.isError && <>
          <p className="break-all">{detail.entity.source_system} · {detail.entity.plant_id} / {detail.entity.generator_id ?? '—'} · {detail.entity.entity_id}</p>
          <button className={buttonStyle} onClick={() => download(detail, `electricity-history-${entityId}-${historyOffset}.json`)}>{t.exportHistory}</button>
          <div role="region" aria-label={t.historyScroll} tabIndex={0} className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300"><table aria-label={t.history} className="w-full text-sm"><thead><tr>{[t.time, t.selected, t.name, t.capacity, t.status, t.claim, t.hash, t.contradiction].map(h => <th scope="col" className="p-2 text-left" key={h}>{h}</th>)}</tr></thead><tbody>{detail.claims.map(c => <tr key={c.claim_id}>
            <td className="p-2">{c.claim.valid_from} → {c.claim.valid_to ?? t.open}</td><td className="p-2">{c.selected_at ? t.yes : t.no}</td><td className="p-2">{c.claim.name}</td><td className="p-2">{c.claim.nameplate_mw}</td><td className="p-2">{c.claim.status} · {c.claim.review_state}</td><td className="p-2 break-all min-w-40">{c.claim_id}</td><td className="p-2 break-all min-w-40">{c.claim.receipt_sha256}</td><td className="p-2 break-all min-w-40">{c.conflicting_claim_ids.join(' · ') || t.none}</td>
          </tr>)}</tbody></table></div>
          <div className="flex flex-wrap gap-2"><button className={buttonStyle} disabled={!historyOffset} onClick={() => setHistoryOffset(Math.max(0, historyOffset - 20))}>{t.historyPrev}</button><button className={buttonStyle} disabled={detail.next_offset === null} onClick={() => setHistoryOffset(detail.next_offset)}>{t.historyNext}</button></div>
          <details><summary className="cursor-pointer">{t.disclosures}</summary><ul className="space-y-3">{detail.sources.map((s, i) => <li key={i} className="break-all"><dl>{[[t.authority, s.authority], [t.hash, s.sha256], [t.license, s.license], [t.published, s.published_at || t.unknown], [t.retrieved, s.retrieved_at]].map(([label, value]) => <div key={label}><dt className="font-semibold">{label}</dt><dd>{value}</dd></div>)}</dl><a className="text-cyan-300 underline" href={s.source_url} rel="noreferrer" target="_blank">{t.sourceLink}</a></li>)}</ul></details>
        </>}
      </section>}
    </>}
  </section>
}
