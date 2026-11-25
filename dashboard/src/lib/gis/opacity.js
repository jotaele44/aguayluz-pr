// Mirrored from spiderweb-pr server/frontend/src/spatial/gis/opacity.ts (jotaele44/spiderweb-pr#435),
// transpiled to JavaScript for this JSX dashboard. Keep behaviour identical to the source;
// change the TypeScript original first, then re-mirror.
const OPACITY_PROPERTY = {
    fill: "fill-opacity",
    line: "line-opacity",
    circle: "circle-opacity",
    symbol: "icon-opacity",
    heatmap: "heatmap-opacity",
    raster: "raster-opacity",
    "fill-extrusion": "fill-extrusion-opacity",
};
const baseOpacity = new WeakMap();
export function opacityProperty(layerType) {
    return OPACITY_PROPERTY[layerType] ?? null;
}
export function scaledOpacity(base, factor) {
    const clamped = Math.min(1, Math.max(0, factor));
    if (typeof base === "number")
        return base * clamped;
    if (base === undefined || base === null)
        return clamped;
    // Data-driven base expression: scale it rather than replace it.
    return ["*", base, clamped];
}
/** Apply `factor` to every style layer drawing from `sourceId`; returns how many were changed. */
export function setSourceOpacity(map, sourceId, factor) {
    const style = map.getStyle();
    let cache = baseOpacity.get(map);
    if (!cache) {
        cache = new Map();
        baseOpacity.set(map, cache);
    }
    let changed = 0;
    for (const layer of style.layers ?? []) {
        if (!("source" in layer) || layer.source !== sourceId)
            continue;
        const property = opacityProperty(layer.type);
        if (!property)
            continue;
        if (!cache.has(layer.id))
            cache.set(layer.id, map.getPaintProperty(layer.id, property));
        map.setPaintProperty(layer.id, property, scaledOpacity(cache.get(layer.id), factor));
        changed += 1;
    }
    return changed;
}
