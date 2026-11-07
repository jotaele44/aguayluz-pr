# GIS viewer API (`/gis/*`) and map tools

The `/gis/*` API backs the GIS tools on the Map page (`dashboard/src/components/AssetMap.jsx`):
a layer catalog, identify, search, area-of-interest query, export, saved views, print,
and two AguaYLuz-specific tools, **dependency tracing** and **outage scenarios**.
It serves the corpora the rest of the API already serves; it adds no data source.

## Contracts (mirrored from spiderweb-pr)

spiderweb-pr is the federation's spatial contract authority. These files are copied
byte-for-byte from it (jotaele44/spiderweb-pr#435):

| Schema | Contract | Used by |
|---|---|---|
| `schemas/gis_layer_catalog_v1.schema.json` | `gis-layer-catalog/1.0` | `GET /gis/catalog` |
| `schemas/gis_query_v1.schema.json` | `gis-query/1.0` | `POST /gis/query`, `POST /gis/export` |
| `schemas/gis_scenario_result_v1.schema.json` | `gis-scenario-result/1.0` | `POST /gis/scenario` |

`src/aguayluz/gis_query.py` and `server/backend/gis_api.py` are spiderweb copies that differ
only in one import line. `src/aguayluz/gis_geodesy.py` ports the WGS84 validation and Vincenty
distance from `federation/spatial_core.py`, which sits outside the installed package.

## Catalog

`config/gis_layer_catalog.yaml`, built by `src/aguayluz/gis_catalog.py`:

| Layer | Source | Notes |
|---|---|---|
| `power_assets`, `water_assets`, `wastewater_assets` | `data/utility_assets.jsonl` via `/assets.geojson` | Classified by `asset_subtype`. Capacity symbology is declared data-blocked: the corpus has no capacity or output fields. |
| `asset_dependencies` | `data/alert_dependency_edges.jsonl` | Links drawn as lines where both ends have coordinates. |
| `alerts` | `/alerts.geojson` | Time field `start_at`. |
| `river_gauges` | `/hydromet/gauges.geojson` | Latest NWPS observation per gauge. |
| `municipios`, `barrios` | `data/geo/` | Identify context and documents. |
| `cave_karst` | none | **Blocked.** `cave_karst_api.py` redacts coordinates unless `location_disclosure` is `public_exact`, and every record is `public_generalized`, so no geometry is published. |

Every layer is also served at `GET /gis/layers/{layer_id}.geojson`. Zoom thresholds stay
`null` until measured. Only `PUBLIC`, non-blocked layers are exportable.

## Endpoints

| Endpoint | What it does |
|---|---|
| `GET /gis/catalog` | The catalog document, with request-time `data_available`. |
| `GET /gis/identify?lon&lat&tol_m&layers` | Features near a point, nearest first, plus the containing municipio and barrio. |
| `GET /gis/search?q` | Accent-insensitive search over each layer's `search_fields`, plus typed coordinates. |
| `POST /gis/query` | Point, radius, bbox or polygon query; `excluded_count` reports features without usable geometry. |
| `POST /gis/export` | The same selection as GeoJSON or CSV; 403 for non-exportable layers. |
| `GET /gis/trace?feature_id&direction&max_hops` | Recorded dependency links up- or downstream of an asset. |
| `POST /gis/scenario` | What would lose service if the selected assets went out of service. |
| `GET /gis/features/{layer}/{id}/history` | Alert timeline for an asset, or the latest gauge observation. |
| `GET /gis/features/{layer}/{id}/documents` | An asset's `source_ref`, or a municipio's JP flood document binding when `data/jp_flood_documents.json` has been built. |

## Dependency links are proxies

The 87 `power_node → hydro_asset` links in `data/alert_dependency_edges.jsonl` were inferred
from distance (confidence about 47, `evidence_required: true`): they are **not verified
circuits**. Tracing and scenarios therefore carry path evidence:

- each traced or impacted feature reports the `edge_id` that reached it, the **weakest
  confidence** on its path and whether any link on that path needs evidence;
- results set `unverified_links_used`, and the Map tools show
  "Proximity proxy, not a verified circuit" whenever it is true;
- scenarios are always `evidence_state: HYPOTHESIS` and `persisted: false`, and never enter
  exports or federation streams.

Scenario municipios come from an asset's recorded `municipality` when it names a municipio,
otherwise from the municipio containing its coordinates. Most assets record "unknown" or the
island-level "Puerto Rico".

## Map tools

Open **Spatial tools** on the Map page:

- **Map:** search, home/back/forward extent, Shift-drag zoom to box, scale bar, cursor
  coordinates, opacity for municipios, barrios, alerts and gauges, save view to URL, named
  bookmarks, and print to PNG with a JSON sidecar.
- **Area, Identify, Polygon query** (with export), plus the existing Measure, Buffer and Nearest.
- **Dependencies:** click an asset; choose "What it depends on" or "What depends on it".
- **Scenario:** click assets to mark them out of service, then run.

## Tests

`tests/test_gis_query.py`, `tests/test_gis_catalog.py`, `tests/test_gis_network.py`,
`tests/test_gis_api.py`; `dashboard/src/lib/gis/*.test.js` and
`dashboard/src/components/SpatialToolsPanel.gis.test.jsx`. GUI parity:
capability `gis-viewer-and-dependency-analysis` in `.federation/gui-capabilities.json`.
