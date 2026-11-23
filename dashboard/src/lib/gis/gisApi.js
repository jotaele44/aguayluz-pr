// Mirrored from spiderweb-pr server/frontend/src/spatial/gis/gisApi.ts (jotaele44/spiderweb-pr#435),
// transpiled to JavaScript for this JSX dashboard. Keep behaviour identical to the source;
// change the TypeScript original first, then re-mirror.
async function readJson(response) {
    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
            const body = (await response.json());
            if (typeof body.detail === "string")
                detail = `${detail}: ${body.detail}`;
        }
        catch { /* non-JSON error body */ }
        throw new Error(detail);
    }
    return (await response.json());
}
export function polygonQueryBody(polygon, layers) {
    return {
        contract_version: "gis-query/1.0",
        geometry: { type: "polygon", geojson: polygon.geometry },
        layers,
    };
}
export function createGisClient(apiBase, fetchImpl = fetch) {
    const post = (path, body) => fetchImpl(`${apiBase}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    return {
        async catalog(signal) {
            return readJson(await fetchImpl(`${apiBase}/gis/catalog`, { signal }));
        },
        async identify(lon, lat, layers, toleranceM = 25) {
            const params = new URLSearchParams({ lon: String(lon), lat: String(lat), tol_m: String(toleranceM) });
            if (layers.length)
                params.set("layers", layers.join(","));
            return readJson(await fetchImpl(`${apiBase}/gis/identify?${params.toString()}`));
        },
        async search(query, signal) {
            const params = new URLSearchParams({ q: query });
            const body = await readJson(await fetchImpl(`${apiBase}/gis/search?${params.toString()}`, { signal }));
            return body.hits;
        },
        async queryPolygon(polygon, layers) {
            return readJson(await post("/gis/query", polygonQueryBody(polygon, layers)));
        },
        async exportPolygon(polygon, layers, format) {
            const response = await post("/gis/export", { ...polygonQueryBody(polygon, layers), format });
            if (!response.ok)
                await readJson(response);
            return response.blob();
        },
    };
}
