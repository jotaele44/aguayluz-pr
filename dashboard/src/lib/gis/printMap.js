// Mirrored from spiderweb-pr server/frontend/src/spatial/gis/printMap.ts (jotaele44/spiderweb-pr#435),
// transpiled to JavaScript for this JSX dashboard. Keep behaviour identical to the source;
// change the TypeScript original first, then re-mirror.
/**
 * Plain text of a source attribution (which MapLibre styles carry as HTML,
 * e.g. `<a href=…>© OpenStreetMap</a>`). Parsed into an inert DOMParser
 * document — never executed, never inserted into the page — and only its text
 * content is kept (minus any angle brackets), so no markup survives into the
 * print footer or sidecar.
 */
export function plainTextAttribution(html) {
    const text = new DOMParser().parseFromString(html, "text/html").body.textContent;
    // Drop every angle bracket left in the text so nothing tag-shaped survives
    // even if a later consumer renders this string as HTML.
    return text.replace(/[<>]/g, "").replace(/\s+/g, " ").trim();
}
/** Metres per CSS pixel at the map centre (Web Mercator). */
export function metresPerPixel(lat, zoom) {
    return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom;
}
/** A round scale-bar length (1/2/5 × 10^n m) no wider than maxPx pixels. */
export function scaleBar(lat, zoom, maxPx = 120) {
    const mpp = metresPerPixel(lat, zoom);
    const maxM = mpp * maxPx;
    const magnitude = 10 ** Math.floor(Math.log10(maxM));
    const step = [5, 2, 1].map((f) => f * magnitude).find((m) => m <= maxM) ?? magnitude;
    return { px: step / mpp, label: step >= 1000 ? `${step / 1000} km` : `${step} m` };
}
export function buildPrintSidecar(input) {
    return {
        contract: "spiderweb-map-print/1.0",
        producer_repo: input.producerRepo,
        generated_at: (input.now ?? new Date()).toISOString(),
        bbox: input.bbox,
        center: input.center,
        zoom: Math.round(input.zoom * 100) / 100,
        bearing: Math.round(input.bearing),
        pitch: Math.round(input.pitch),
        layers: Object.entries(input.layers).map(([layer_id, opacity]) => ({ layer_id, opacity })),
        attribution: input.attribution,
        scale_text: scaleBar(input.center[1], input.zoom).label,
    };
}
function download(blob, filename) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function downloadBlob(blob, filename) {
    download(blob, filename);
}
/** Capture the map on its next render (the drawing buffer is valid inside the render event). */
export function printMap(map, sidecar) {
    return new Promise((resolve, reject) => {
        map.once("render", () => {
            try {
                const source = map.getCanvas();
                const ratio = source.width / source.clientWidth || 1;
                const footer = Math.round(56 * ratio);
                const out = document.createElement("canvas");
                out.width = source.width;
                out.height = source.height + footer;
                const ctx = out.getContext("2d");
                if (!ctx)
                    throw new Error("2D canvas unavailable");
                ctx.fillStyle = "#ffffff";
                ctx.fillRect(0, 0, out.width, out.height);
                ctx.drawImage(source, 0, 0);
                ctx.fillStyle = "#000000";
                ctx.font = `${Math.round(12 * ratio)}px sans-serif`;
                const bar = scaleBar(sidecar.center[1], sidecar.zoom);
                const y = source.height + Math.round(20 * ratio);
                ctx.fillRect(Math.round(12 * ratio), y, Math.round(bar.px * ratio), Math.max(2, Math.round(3 * ratio)));
                ctx.fillText(bar.label, Math.round((18 + bar.px) * ratio), y + Math.round(4 * ratio));
                ctx.fillText(`N ↑ (bearing ${sidecar.bearing}°)`, Math.round(200 * ratio), y + Math.round(4 * ratio));
                const [w, s, e, n] = sidecar.bbox.map((v) => v.toFixed(4));
                ctx.fillText(`Extent W ${w} S ${s} E ${e} N ${n} · z${sidecar.zoom} · ${sidecar.generated_at}`, Math.round(12 * ratio), y + Math.round(22 * ratio));
                ctx.fillText(sidecar.attribution.slice(0, 160), Math.round(12 * ratio), y + Math.round(36 * ratio));
                const stamp = sidecar.generated_at.replace(/[:.]/g, "-");
                out.toBlob((blob) => {
                    if (!blob) {
                        reject(new Error("canvas export failed"));
                        return;
                    }
                    download(blob, `${sidecar.producer_repo}-map-${stamp}.png`);
                    download(new Blob([JSON.stringify(sidecar, null, 2)], { type: "application/json" }), `${sidecar.producer_repo}-map-${stamp}.json`);
                    resolve();
                }, "image/png");
            }
            catch (error) {
                reject(error instanceof Error ? error : new Error(String(error)));
            }
        });
        map.triggerRepaint();
    });
}
