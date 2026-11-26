// Mirrored from spiderweb-pr server/frontend/src/spatial/gis/gis.test.ts (jotaele44/spiderweb-pr#435).
import { describe, expect, it, vi } from "vitest";
import { decodeMapState, deleteBookmark, encodeMapState, readBookmarks, saveBookmark } from "./mapState";
import { ExtentHistory } from "./extentHistory";
import { googleMapsPointUrl, googleStreetViewUrl } from "./externalLinks";
import { drawPolygonCollection, formatArea, polygonFromVertices, ringAreaM2 } from "./measure";
import { createGisClient, polygonQueryBody } from "./gisApi";
import { buildPrintSidecar, metresPerPixel, plainTextAttribution, scaleBar } from "./printMap";
import { scaledOpacity, setSourceOpacity } from "./opacity";
function memoryStorage() {
    const data = new Map();
    return {
        getItem: (key) => data.get(key) ?? null,
        setItem: (key, value) => void data.set(key, value),
    };
}
describe("map state (Salvar)", () => {
    const state = { center: [-66.5, 18.22], zoom: 8.5, bearing: 12, pitch: 30, layers: { municipios: 1, gazetteer_pr_domestic_names: 0.6 } };
    it("round-trips camera and layer opacities through the URL hash", () => {
        const hash = `#${encodeMapState(state)}`;
        expect(decodeMapState(hash)).toEqual(state);
    });
    it("rejects malformed or out-of-range hashes and drops bad layer entries", () => {
        expect(decodeMapState("#map=99/18/-66/0/0")).toBeNull();
        expect(decodeMapState("#map=8/18/-66")).toBeNull();
        expect(decodeMapState("")).toBeNull();
        expect(decodeMapState("#map=8/18/-66/0/0&layers=ok:0.5,Bad-Id:1,nope:7")?.layers).toEqual({ ok: 0.5 });
    });
    it("saves, replaces and deletes named bookmarks", () => {
        const storage = memoryStorage();
        saveBookmark(storage, "Arecibo", state, new Date("2026-10-31T00:00:00Z"));
        saveBookmark(storage, "Arecibo", { ...state, zoom: 10 });
        expect(readBookmarks(storage)).toHaveLength(1);
        expect(readBookmarks(storage)[0].state.zoom).toBe(10);
        expect(deleteBookmark(storage, "Arecibo")).toEqual([]);
        storage.setItem("spiderweb_gis_bookmarks", "{not json");
        expect(readBookmarks(storage)).toEqual([]);
    });
});
describe("extent history", () => {
    it("walks back and forward without re-recording the jumps", () => {
        const history = new ExtentHistory();
        const a = { center: [-66, 18], zoom: 8 };
        const b = { center: [-66.1, 18.1], zoom: 10 };
        const c = { center: [-66.2, 18.2], zoom: 12 };
        history.push(a);
        history.push(b);
        history.push(b);
        history.push(c);
        expect(history.back()).toEqual(b);
        history.push(b); // the moveend caused by back() is suppressed
        expect(history.back()).toEqual(a);
        expect(history.canBack).toBe(false);
        expect(history.forward()).toEqual(b);
        history.push(b);
        history.push({ center: [-65, 18], zoom: 9 }); // new branch drops c
        expect(history.canForward).toBe(false);
    });
});
describe("external hand-off", () => {
    it("builds lat,lon Google Maps URLs rounded to 6 decimals", () => {
        expect(googleMapsPointUrl(-66.71561234, 18.4723)).toBe("https://www.google.com/maps/search/?api=1&query=18.472300%2C-66.715612");
        expect(googleStreetViewUrl(-66.7156, 18.4723)).toContain("map_action=pano&viewpoint=18.472300%2C-66.715600");
        expect(() => googleMapsPointUrl(Number.NaN, 18)).toThrow();
    });
});
describe("area measurement", () => {
    it("matches a planar estimate for a small square near Puerto Rico", () => {
        const ring = [[-66.1, 18.3], [-66.09, 18.3], [-66.09, 18.31], [-66.1, 18.31]];
        const k = (Math.PI / 180) * 6371008.8;
        const planar = 0.01 * k * (0.01 * k * Math.cos((18.305 * Math.PI) / 180));
        expect(ringAreaM2(ring)).toBeGreaterThan(planar * 0.995);
        expect(ringAreaM2(ring)).toBeLessThan(planar * 1.005);
        expect(ringAreaM2([...ring, ring[0]])).toBeCloseTo(ringAreaM2(ring), 6);
        expect(ringAreaM2(ring.slice(0, 2))).toBe(0);
    });
    it("closes drawn polygons and reports units", () => {
        expect(polygonFromVertices([[0, 0], [1, 0]])).toBeNull();
        const polygon = polygonFromVertices([[0, 0], [1, 0], [1, 1]]);
        expect(polygon?.geometry.coordinates[0]).toHaveLength(4);
        expect(drawPolygonCollection([[0, 0], [1, 0]]).features.map((f) => f.geometry.type)).toEqual(["Point", "Point", "LineString"]);
        expect(formatArea(2_500_000)).toMatch(/^2\.50 km²/);
        expect(formatArea(5000)).toMatch(/m² · 1\.24 acres$/);
    });
});
describe("gis api client", () => {
    const polygon = polygonFromVertices([[-66.2, 18.2], [-66.0, 18.2], [-66.0, 18.4]]);
    if (!polygon)
        throw new Error("fixture");
    it("sends gis-query/1.0 polygon bodies", () => {
        expect(polygonQueryBody(polygon, ["municipios"])).toEqual({
            contract_version: "gis-query/1.0",
            geometry: { type: "polygon", geojson: polygon.geometry },
            layers: ["municipios"],
        });
    });
    it("builds identify URLs and surfaces backend error details", async () => {
        const fetchImpl = vi.fn()
            .mockResolvedValueOnce(new Response(JSON.stringify({ hits: [], point: { lon: -66, lat: 18 } }), { status: 200 }))
            .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "unknown layer(s): nope" }), { status: 400 }));
        const client = createGisClient("http://api", fetchImpl);
        await client.identify(-66, 18, ["municipios", "barrios"], 30);
        expect(fetchImpl.mock.calls[0][0]).toBe("http://api/gis/identify?lon=-66&lat=18&tol_m=30&layers=municipios%2Cbarrios");
        await expect(client.queryPolygon(polygon, ["nope"])).rejects.toThrow("HTTP 400: unknown layer(s): nope");
    });
});
describe("print sidecar and scale bar", () => {
    it("picks a round scale length that fits", () => {
        expect(metresPerPixel(0, 0)).toBeCloseTo(156543.03392, 3);
        const bar = scaleBar(18.2, 9, 120);
        expect(["10 km", "20 km", "5 km", "2 km"]).toContain(bar.label);
        expect(bar.px).toBeLessThanOrEqual(120);
    });
    it("reduces HTML attributions to plain text with no surviving markup", () => {
        expect(plainTextAttribution('<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a> contributors')).toBe("© OpenStreetMap contributors");
        expect(plainTextAttribution("<scr<script>ipt>alert(1)</script>Terrain")).not.toMatch(/<|>/);
        expect(plainTextAttribution("<img src=x onerror=alert(1)>Tiles")).toBe("Tiles");
    });
    it("records extent, layers and timestamp", () => {
        const sidecar = buildPrintSidecar({
            producerRepo: "spiderweb-pr", bbox: [-67, 17.9, -65.2, 18.6], center: [-66.1, 18.25], zoom: 8.456,
            bearing: 0, pitch: 0, layers: { municipios: 1 }, attribution: "© OpenStreetMap", now: new Date("2026-10-31T12:00:00Z"),
        });
        expect(sidecar).toMatchObject({ zoom: 8.46, generated_at: "2026-10-31T12:00:00.000Z", layers: [{ layer_id: "municipios", opacity: 1 }] });
    });
});
describe("layer opacity", () => {
    it("scales numeric and expression base opacities", () => {
        expect(scaledOpacity(0.08, 0.5)).toBeCloseTo(0.04);
        expect(scaledOpacity(undefined, 2)).toBe(1);
        expect(scaledOpacity(["get", "o"], 0.5)).toEqual(["*", ["get", "o"], 0.5]);
    });
    it("only touches style layers of the requested source and keeps the original base", () => {
        const paint = new Map([["geo-municipios-fill", 0.08], ["geo-municipios-line", 0.9]]);
        const map = {
            getStyle: () => ({ layers: [
                    { id: "geo-municipios-fill", type: "fill", source: "geo-municipios" },
                    { id: "geo-municipios-line", type: "line", source: "geo-municipios" },
                    { id: "osm", type: "raster", source: "osm" },
                ] }),
            getPaintProperty: (id) => paint.get(id),
            setPaintProperty: (id, _prop, value) => void paint.set(id, value),
        };
        expect(setSourceOpacity(map, "geo-municipios", 0.5)).toBe(2);
        expect(setSourceOpacity(map, "geo-municipios", 0.5)).toBe(2);
        expect(paint.get("geo-municipios-fill")).toBeCloseTo(0.04);
        expect(paint.get("geo-municipios-line")).toBeCloseTo(0.45);
    });
});
