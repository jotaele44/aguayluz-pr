// Mirrored from spiderweb-pr server/frontend/src/spatial/gis/externalLinks.ts (jotaele44/spiderweb-pr#435),
// transpiled to JavaScript for this JSX dashboard. Keep behaviour identical to the source;
// change the TypeScript original first, then re-mirror.
/**
 * Hand-off of a clicked point to Google Maps (documented Maps URLs API, no key).
 * Coordinates are rounded to 6 decimals (~0.1 m) so the link never carries
 * more precision than the click had.
 */
function fixed(value) {
    if (!Number.isFinite(value))
        throw new Error("coordinate must be finite");
    return value.toFixed(6);
}
export function googleMapsPointUrl(lon, lat) {
    return `https://www.google.com/maps/search/?api=1&query=${fixed(lat)}%2C${fixed(lon)}`;
}
export function googleStreetViewUrl(lon, lat) {
    return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${fixed(lat)}%2C${fixed(lon)}`;
}
