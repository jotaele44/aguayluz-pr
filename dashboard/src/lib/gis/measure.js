// Mirrored from spiderweb-pr server/frontend/src/spatial/gis/measure.ts (jotaele44/spiderweb-pr#435),
// transpiled to JavaScript for this JSX dashboard. Keep behaviour identical to the source;
// change the TypeScript original first, then re-mirror.
const EARTH_RADIUS_M = 6371008.8; // mean radius, as @turf/area v7 and federation/spatial_core.py use
/**
 * Geodesic polygon area on the WGS84 sphere (m^2) — the same spherical-excess
 * ring formula @turf/area uses, kept local to avoid another dependency.
 * Accepts an open or closed ring; fewer than 3 distinct vertices -> 0.
 */
export function ringAreaM2(ring) {
    const coords = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]
        ? ring.slice(0, -1)
        : ring;
    if (coords.length < 3)
        return 0;
    const rad = Math.PI / 180;
    let total = 0;
    for (let i = 0; i < coords.length; i += 1) {
        const lower = coords[i];
        const middle = coords[(i + 1) % coords.length];
        const upper = coords[(i + 2) % coords.length];
        total += (upper[0] * rad - lower[0] * rad) * Math.sin(middle[1] * rad);
    }
    return Math.abs((total * EARTH_RADIUS_M * EARTH_RADIUS_M) / 2);
}
export function polygonFromVertices(vertices) {
    if (vertices.length < 3)
        return null;
    return {
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [[...vertices, vertices[0]]] },
    };
}
/** Vertices as points plus the closed polygon once there are three. */
export function drawPolygonCollection(vertices) {
    const polygon = polygonFromVertices(vertices);
    return {
        type: "FeatureCollection",
        features: [
            ...vertices.map((coordinates) => ({
                type: "Feature",
                properties: {},
                geometry: { type: "Point", coordinates },
            })),
            ...(polygon ? [polygon] : vertices.length === 2
                ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: vertices } }]
                : []),
        ],
    };
}
export function formatArea(m2) {
    if (m2 >= 1_000_000)
        return `${(m2 / 1_000_000).toFixed(2)} km² · ${(m2 / 2_589_988.11).toFixed(2)} mi²`;
    return `${Math.round(m2).toLocaleString("en-US")} m² · ${(m2 / 4046.8564224).toFixed(2)} acres`;
}
