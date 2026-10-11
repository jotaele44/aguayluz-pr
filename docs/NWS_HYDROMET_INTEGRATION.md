# NWS hydromet integration

AguaYLuz ingests the Puerto Rico-relevant parts of NOAA/NWS's GIS data catalog into an
**NWS hydromet plane**: frozen source responses, evidence-classed bindings to utility
assets and municipios, and `WEATHER_HAZARD` alerts. This document covers what was wired,
what was not, and why.

## Why

Water and power infrastructure in Puerto Rico is exposed first to rain and river
flooding: turbidity shuts filtration plants, floods reach intakes and pump stations, and
reservoirs spill. The existing corpus had NWS *warnings* (`ingest_nws_alerts.py`) and NHC
storm positions, but no observed river condition against NWS's own flood thresholds.

## The catalog that prompted this

[`weather.gov/gis/IDP-GISRestMetadata`](https://www.weather.gov/gis/IDP-GISRestMetadata)
is a legacy catalog. Its ISO 19115 metadata is stamped 2020-03-12, and every endpoint
points at `idpgis.ncep.noaa.gov`, which NWS shut down on 2023-06-30 (SCN 23-01). The live
GIS services are on `mapservices.weather.noaa.gov`. Each entry was checked against Puerto
Rico (live probes, 2026-10-06/07):

| Catalog entry | Decision | Reason |
|---|---|---|
| AHPS River Gauge Current and Forecast Flood Stages | **Wired** via the NWPS API | 118 PR gauges, 82 with published thresholds; AHPS became NWPS in 2024 |
| River Forecast Centers Daily QPE | **Wired** via the Stage IV PR GeoTIFFs | dedicated PR grid on `water.noaa.gov`; the CloudGIS `rfc_qpe` mosaic does not cover PR |
| Active Atlantic & Caribbean Hurricanes | Planned (NHC cone footprint) | cone KMZ is already linked from `CurrentStorms.json` |
| Drought Outlook | Planned (CPC, "US and Puerto Rico" layer) | PR polygons present |
| Watches, Warnings and Advisories | **Display-only overlay** (not data) | already ingested from `api.weather.gov`; the CloudGIS layer is shown on the map, off by default |
| Radar Base Reflectivity | **Display-only overlay** (not data) | MRMS mosaic covers PR (TJUA); shown on the map, off by default |
| WPC excessive rainfall / QPF / winter, RFC flash-flood guidance, CPC hazards and temperature outlooks, NDFD, SPC, NOHRSC, APRFC | Not wired | CONUS-only per their own extents |
| NDGD air quality (PM2.5, ozone, dust, smoke) | Not wired | PR coverage unverified; outside the water/power scope |
| Reference maps (zones, CWA, NWM lakes) | Not wired | no utility signal by themselves |

## NWPS river gauges (wired)

| Step | Endpoint / file |
|---|---|
| Bulk status | `GET https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-67.95&bbox.ymin=17.85&bbox.xmax=-65.2&bbox.ymax=18.55&srid=EPSG_4326` |
| Per-gauge detail (thresholds, `usgsId`, county) | `GET https://api.water.noaa.gov/nwps/v1/gauges/{lid}`, refreshed when missing or older than 24 h |
| Registry | `config/hydromet_sources.v1.json` (URLs, cadence, staleness limits) |
| Ingest | `scripts/ingest_nwps_gauges.py` (`--dry-run`, `--src`, `--details-src`, `--data-dir`) |
| Schedule | every `scripts/refresh.py` cadence (15 min, daily, weekly, all), optional |

**Pipeline.** Response bytes are hashed (and kept under `data/hydromet_snapshots/`,
gitignored) before parsing. Each run must close
`SOURCE = RETAINED + EXCLUDED + UNRESOLVED` over the bulk response or it fails closed
with a FAIL receipt. A record revision is written only when the *material state* changes
(flood category, thresholds, service state, `usgsId`); the current stage is rewritten in
`data/nwps_gauge_state.jsonl` every run. Committed files:

- `data/hydromet_records.jsonl` — `HazardRecord` revisions (family `HYDROMETEOROLOGY`)
- `data/hydromet_relationships.jsonl` — bindings
- `data/hydromet_manifestations.jsonl` — frozen responses, pruned to those still referenced
- `data/hydromet_receipts.json` — last attempt / last success per source
- `data/nwps_gauge_state.jsonl` — current per-gauge snapshot

**Bindings and evidence.**

| Binding | Evidence class | Notes |
|---|---|---|
| gauge → `USGS_<usgsId>` asset | `STABLE_ID` | 108 gauges publish a `usgsId`; all match existing assets |
| gauge → municipio, polygon and NWPS county agree | `POINT_IN_POLYGON_WITH_ALIAS` | 102 gauges |
| gauge → municipio, no county published | `POINT_IN_POLYGON` | |
| coastal gauge just offshore of the generalized coastline, county agrees, ≤ 1.5 km | `ALIAS_WITH_SPATIOTEMPORAL_SUPPORT` | distance recorded |
| polygon and county disagree (boundary rivers) | `UNRESOLVED` | 12 gauges; candidate kept, never adopted |

**Alerts** (`src/aguayluz/alert_promotion/hydromet.py`, marker `_nwpsflood_`). A flood
episode opens on the first revision observed at action or above and closes on the first
revision observed below action. A missing or old observation neither opens nor closes an
episode. Severity is the peak category: action 2, minor 3, moderate 4 (critical: Hub
push/SMS), major 5. Boundary-river gauges name both candidate municipios and go to
`needs_review`. These are observations against NWS thresholds, not issued warnings.

**Dashboard.** Sidebar → **NWS Hydromet**: source freshness (FRESH / STALE / FAILED /
NEVER), last attempt and success, source arithmetic, byte SHA-256, the latest error, a
**Refresh now** control (key-gated when `API_SECRET_KEY` is set), and the gauge table with
an in-flood filter. On **Map**, the **River gauges** layer colours gauges by flood category.

## Stage IV rainfall (wired)

| Step | Endpoint / file |
|---|---|
| Daily grids | `GET https://water.noaa.gov/resources/downloads/precip/stageIV/YYYY/MM/DD/nws_precip_{1day,last7days,last30days}_YYYYMMDD_pr.tif` |
| Registry | `config/hydromet_sources.v1.json` (`stage_iv_pr`: URL template, windows, cadence 24 h, stale after 48 h) |
| Ingest | `scripts/ingest_stage_iv_pr.py` (`--dry-run`, `--src-dir` + `--date`, `--data-dir`, `--lookback-days`, `--backfill-days`) |
| Schedule | `scripts/refresh.py` daily, weekly and all cadences, optional |

**The grid.** Each file is a 205 × 205 HRAP grid (polar stereographic, 4.76 km cells) with
four float32 bands in inches: observation, PRISM normal, departure from normal and
percent of normal. The GDAL `data_time` tag is the window's closing 12Z; a file whose tag
disagrees with its dated name fails closed. The run finds the newest day with a 1-day
file (looking back 4 days), fetches its 7- and 30-day files, and back-fills missing 1-day
files for the 3 days before it.

**Pipeline.** File bytes are hashed (and kept under `data/hydromet_snapshots/stage_iv_pr/`,
gitignored) before they are opened. Each file is summarised per municipio: mean and
maximum observed rainfall, mean PRISM normal, departure, percent of normal and cell count.
Arithmetic per file is 78 municipio zones = RETAINED (valid cells) + UNRESOLVED. One
record per municipio × window × data day; a re-processed file supersedes the earlier
record for the same event. 1-day history is kept 30 days; 7- and 30-day windows keep only
the newest day.

**Bindings and evidence.**

| Binding | Evidence class | Notes |
|---|---|---|
| zone → municipio, HRAP cell centres inside the Census polygon | `POINT_IN_POLYGON`, `FULLY_WITHIN` | every one of the 78 municipios holds at least one cell centre (Cataño: 1) |
| zone → municipio, cells the polygon only touches | `PROXIMITY`, `PARTIAL` | fallback for a municipio too small to hold a centre; alerts go to review |
| no cell at all | none (`UNRESOLVED` record) | never widened to island-wide |

**Alerts** (marker `_qpeheavy_`). One alert per municipio and 1-day window at a threshold:
municipio mean ≥ 3 in → severity 2, any cell ≥ 6 in → severity 3. Stage IV is a
post-event analysis published after the 12Z day closes, so these stay below the critical
push/SMS floor and serve turbidity, reservoir-inflow and landslide follow-up. An alert is
`active` for 72 h after the window ends, then `closed`. Coordinates are the municipio
centroid (`approximate`); linked assets are those in the municipio. The thresholds are
named constants in `src/aguayluz/hazard_adapters/stage_iv_qpe.py`.

**Dashboard.** **NWS Hydromet → Rainfall by municipio**: 1-, 7- or 30-day window, data
day picker (1-day history), municipio mean, wettest cell, PRISM normal, percent of
normal, cell count, heavy-rain flag, and the source file's SHA-256 and retrieval time.
The Stage IV source card shows freshness, arithmetic and **Refresh now**. On **Map →
Municipio fill → Rainfall**, municipios are tinted by the latest 1-day mean, with the
data day stated.

## Display-only map overlays

**Map → NWS live overlays** offers **NWS radar** and **NWS warnings**. The browser loads
them straight from CloudGIS as ArcGIS `export` image tiles:

| Overlay | Service |
|---|---|
| NWS radar | `https://mapservices.weather.noaa.gov/eventdriven/rest/services/radar/radar_base_reflectivity/MapServer` |
| NWS warnings | `https://mapservices.weather.noaa.gov/eventdriven/rest/services/WWA/watch_warn_adv/MapServer` (layer 1, all watches/warnings/advisories) |

They are off by default, so the map makes no request to NWS until one is turned on. While
shown, tiles are re-requested every 5 minutes, the panel shows when they were requested and
any tile failure, and it states they are not stored or validated. They are classified
`client_only` in `.federation/gui-capabilities.json` (`nws-cloudgis-map-overlays`): no
backend, no ingestion, no alerts.

## Known limitations

- NWS issues no stage forecasts for Puerto Rico points; only observations are carried.
  NWM v3 short-range streamflow exists for 76 of the gauges' reaches
  (`/nwps/v1/reaches/{reachId}/streamflow`) and is a candidate follow-up.
- Gauges without published thresholds report `not_defined` and never raise an alert.
- The first observed revision of a flood already in progress starts the episode at that
  observation, not at the true onset.
- Stage IV arrives after the 12Z day closes and is provisional; it reports rainfall that
  fell, not impact. HRAP cells are 4.76 km, so a municipio mean smooths convective peaks
  (the wettest-cell value is kept for that reason). PRISM normals cover land cells only.
- At 30 days of 1-day history the Stage IV rows add about 5 MB to the committed hydromet
  files; rows are written without null fields to keep that down.
