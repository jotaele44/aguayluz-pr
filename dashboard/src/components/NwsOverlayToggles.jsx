import { NWS_CLOUDGIS_OVERLAYS, OVERLAY_ATTRIBUTION } from '@/lib/nws-cloudgis-overlays'

const timeOf = (ms) => new Date(ms).toLocaleTimeString()

function statusText(overlay, status) {
  if (status?.state === 'error') return `${overlay.label}: unavailable from NWS (${status.message})`
  if (status?.state === 'live') return `${overlay.label}: live · tiles loaded ${timeOf(status.at)}`
  return `${overlay.label}: loading from NWS…`
}

// Toggles for the display-only NWS CloudGIS overlays on the map. State lives in
// AssetMap (from the map's tile events); this component only renders the controls, the
// per-overlay load status and the "not stored or validated" note.
export default function NwsOverlayToggles({ active = {}, status = {}, onToggle }) {
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
          <span className={status[overlay.id]?.state === 'error' ? 'text-red-300' : 'text-slate-500'}>
            {statusText(overlay, status[overlay.id])}
          </span>
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
