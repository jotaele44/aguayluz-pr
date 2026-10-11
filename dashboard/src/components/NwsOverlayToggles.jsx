import { NWS_CLOUDGIS_OVERLAYS, OVERLAY_ATTRIBUTION } from '@/lib/nws-cloudgis-overlays'

// Toggles for the display-only NWS CloudGIS overlays on the map. State lives in
// AssetMap; this component only renders the controls, the per-overlay load status and
// the "not stored or validated" note.
export default function NwsOverlayToggles({ active = {}, errors = {}, loadedAt = {}, onToggle }) {
  return (
    <div className="mt-1.5" data-testid="nws-overlay-toggles">
      <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">NWS live overlays · display only</div>
      <div className="grid grid-cols-2 gap-1.5">
        {NWS_CLOUDGIS_OVERLAYS.map((overlay) => {
          const on = Boolean(active[overlay.id])
          return (
            <button
              key={overlay.id}
              type="button"
              aria-pressed={on}
              title={overlay.description}
              onClick={() => onToggle?.(overlay.id)}
              className={`rounded border px-2 py-1 text-[11px] transition ${on ? 'border-sky-400/50 bg-slate-900 text-sky-200' : 'border-slate-800 bg-slate-950/70 text-slate-500 hover:text-slate-300'}`}
            >
              {overlay.label}
            </button>
          )
        })}
      </div>
      {NWS_CLOUDGIS_OVERLAYS.filter((o) => active[o.id]).map((overlay) => (
        <div key={overlay.id} aria-live="polite" className="mt-1 text-[10px] leading-relaxed">
          {errors[overlay.id]
            ? <span className="text-red-300">{overlay.label}: unavailable from NWS ({errors[overlay.id]})</span>
            : <span className="text-slate-500">{overlay.label}: live{loadedAt[overlay.id] ? ` · requested ${new Date(loadedAt[overlay.id]).toLocaleTimeString()}` : ''}</span>}
        </div>
      ))}
      {NWS_CLOUDGIS_OVERLAYS.some((o) => active[o.id]) && (
        <p className="mt-1 text-[10px] leading-relaxed text-slate-600">
          Loaded directly from {OVERLAY_ATTRIBUTION}; not stored or validated by AguaYLuz.
        </p>
      )}
    </div>
  )
}
