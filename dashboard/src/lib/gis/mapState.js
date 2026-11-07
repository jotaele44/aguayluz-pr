// Mirrored from spiderweb-pr server/frontend/src/spatial/gis/mapState.ts (jotaele44/spiderweb-pr#435),
// transpiled to JavaScript for this JSX dashboard. Keep behaviour identical to the source;
// change the TypeScript original first, then re-mirror.
/**
 * Saved map state ("Salvar"): camera + active layers + per-layer opacity,
 * serialised into the URL hash so a view can be shared or restored, plus named
 * bookmarks in localStorage. Pure apart from the Storage argument.
 *
 * Hash format: `#map=<zoom>/<lat>/<lon>/<bearing>/<pitch>&layers=<id>:<opacity>,...`
 */
export const BOOKMARK_STORAGE_KEY = "spiderweb_gis_bookmarks";
const LAYER_ID = /^[a-z0-9_]+$/;
function finite(value, min, max) {
    return Number.isFinite(value) && value >= min && value <= max ? value : null;
}
export function encodeMapState(state) {
    const [lon, lat] = state.center;
    const camera = [
        state.zoom.toFixed(2),
        lat.toFixed(5),
        lon.toFixed(5),
        Math.round(state.bearing).toString(),
        Math.round(state.pitch).toString(),
    ].join("/");
    const layers = Object.entries(state.layers)
        .filter(([id]) => LAYER_ID.test(id))
        .map(([id, opacity]) => `${id}:${Math.round(Math.min(1, Math.max(0, opacity)) * 100) / 100}`)
        .join(",");
    return `map=${camera}&layers=${layers}`;
}
export function decodeMapState(hash) {
    const params = new URLSearchParams(hash.replace(/^#/, ""));
    const camera = params.get("map");
    if (!camera)
        return null;
    const parts = camera.split("/").map(Number);
    if (parts.length !== 5)
        return null;
    const zoom = finite(parts[0], 0, 24);
    const lat = finite(parts[1], -90, 90);
    const lon = finite(parts[2], -180, 180);
    const bearing = finite(parts[3], -360, 360);
    const pitch = finite(parts[4], 0, 85);
    if (zoom === null || lat === null || lon === null || bearing === null || pitch === null)
        return null;
    const layers = {};
    for (const entry of (params.get("layers") ?? "").split(",")) {
        if (!entry)
            continue;
        const [id, rawOpacity] = entry.split(":");
        const opacity = finite(Number(rawOpacity ?? "1"), 0, 1);
        if (LAYER_ID.test(id) && opacity !== null)
            layers[id] = opacity;
    }
    return { center: [lon, lat], zoom, bearing, pitch, layers };
}
export function readBookmarks(storage) {
    try {
        const raw = JSON.parse(storage.getItem(BOOKMARK_STORAGE_KEY) ?? "[]");
        if (!Array.isArray(raw))
            return [];
        return raw.filter((item) => typeof item === "object" && item !== null &&
            typeof item.name === "string" &&
            decodeMapState(`#${encodeMapState(item.state)}`) !== null);
    }
    catch {
        return [];
    }
}
export function saveBookmark(storage, name, state, now = new Date()) {
    const trimmed = name.trim();
    if (!trimmed)
        return readBookmarks(storage);
    const next = [
        ...readBookmarks(storage).filter((bookmark) => bookmark.name !== trimmed),
        { name: trimmed, savedAt: now.toISOString(), state },
    ];
    storage.setItem(BOOKMARK_STORAGE_KEY, JSON.stringify(next));
    return next;
}
export function deleteBookmark(storage, name) {
    const next = readBookmarks(storage).filter((bookmark) => bookmark.name !== name);
    storage.setItem(BOOKMARK_STORAGE_KEY, JSON.stringify(next));
    return next;
}
