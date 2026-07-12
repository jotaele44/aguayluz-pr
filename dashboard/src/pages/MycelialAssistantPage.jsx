import { useState } from 'react'
import { Sprout, ShieldAlert } from 'lucide-react'
import { postMycelialQuery } from '@/lib/api'

const DEFAULTS = {
  rain_72h_mm: 20,
  humidity_pct: 82,
  temperature_c: 24,
  canopy_pct: 70,
  soil_moisture_pct: 65,
  organic_matter: 'high',
  wind_kph: 8,
  access_status: 'unknown',
}

function NumberField({ label, name, value, onChange }) {
  return (
    <label className="space-y-1 text-sm text-slate-300">
      <span>{label}</span>
      <input
        type="number"
        name={name}
        value={value}
        onChange={onChange}
        className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
      />
    </label>
  )
}

export default function MycelialAssistantPage() {
  const [query, setQuery] = useState('¿Qué condiciones favorecen la fructificación de hongos saprófitos?')
  const [conditions, setConditions] = useState(DEFAULTS)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const changeCondition = (event) => {
    const { name, value } = event.target
    setConditions(current => ({ ...current, [name]: value }))
  }

  const submit = async (event) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      setResult(await postMycelialQuery(query, conditions))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <div className="flex items-center gap-2">
          <Sprout className="h-6 w-6 text-emerald-400" />
          <h1 className="text-2xl font-semibold text-slate-100">Mycelial Assistant</h1>
        </div>
        <p className="mt-2 text-sm text-slate-400">
          Evaluación ecológica a escala de hábitat. No autoriza acceso, rutas, recolección ni ubicaciones precisas de taxones sensibles.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-5 rounded-lg border border-slate-800 bg-slate-900/60 p-5">
        <label className="block space-y-1 text-sm text-slate-300">
          <span>Pregunta</span>
          <textarea
            value={query}
            onChange={event => setQuery(event.target.value)}
            rows={3}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
          />
        </label>

        <div className="grid gap-4 md:grid-cols-4">
          <NumberField label="Lluvia 72 h (mm)" name="rain_72h_mm" value={conditions.rain_72h_mm} onChange={changeCondition} />
          <NumberField label="Humedad (%)" name="humidity_pct" value={conditions.humidity_pct} onChange={changeCondition} />
          <NumberField label="Temperatura (°C)" name="temperature_c" value={conditions.temperature_c} onChange={changeCondition} />
          <NumberField label="Dosel (%)" name="canopy_pct" value={conditions.canopy_pct} onChange={changeCondition} />
          <NumberField label="Humedad suelo (%)" name="soil_moisture_pct" value={conditions.soil_moisture_pct} onChange={changeCondition} />
          <NumberField label="Viento (km/h)" name="wind_kph" value={conditions.wind_kph} onChange={changeCondition} />
          <label className="space-y-1 text-sm text-slate-300">
            <span>Materia orgánica</span>
            <select name="organic_matter" value={conditions.organic_matter} onChange={changeCondition} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2">
              <option value="low">Baja</option>
              <option value="medium">Media</option>
              <option value="high">Alta</option>
            </select>
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>Acceso</span>
            <select name="access_status" value={conditions.access_status} onChange={changeCondition} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2">
              <option value="unknown">No verificado</option>
              <option value="public_open">Público, aparente abierto</option>
              <option value="private">Privado</option>
              <option value="closed">Cerrado</option>
            </select>
          </label>
        </div>

        <button disabled={loading || !query.trim()} className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-white disabled:opacity-50">
          {loading ? 'Evaluando…' : 'Evaluar condiciones'}
        </button>
      </form>

      {error && <div className="rounded-md border border-red-800 bg-red-950/40 p-4 text-red-300">{error}</div>}

      {result && (
        <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900/60 p-5">
          {result.status === 'restricted' && (
            <div className="flex gap-2 rounded-md border border-amber-700 bg-amber-950/30 p-3 text-amber-200">
              <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" />
              <span>Solicitud sensible generalizada automáticamente.</span>
            </div>
          )}
          <p className="text-slate-100">{result.answer}</p>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-md bg-slate-950 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">Idoneidad</div>
              <div className="mt-1 text-xl font-semibold capitalize text-emerald-300">{result.suitability?.label} · {result.suitability?.score}/100</div>
            </div>
            <div className="rounded-md bg-slate-950 p-4 md:col-span-2">
              <div className="text-xs uppercase tracking-wide text-slate-500">Ventana ecológica</div>
              <p className="mt-1 text-slate-300">{result.weather_window}</p>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <h2 className="font-medium text-emerald-300">Condiciones favorables</h2>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">{result.favorable_conditions?.map(item => <li key={item}>{item}</li>)}</ul>
            </div>
            <div>
              <h2 className="font-medium text-amber-300">Condiciones desfavorables</h2>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">{result.unfavorable_conditions?.map(item => <li key={item}>{item}</li>)}</ul>
            </div>
          </div>
          <div className="rounded-md border border-slate-800 bg-slate-950 p-3 text-sm text-slate-400">
            Acceso: {result.access?.message}
          </div>
        </section>
      )}
    </div>
  )
}
