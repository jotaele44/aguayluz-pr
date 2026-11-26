# AguaYLuz — Puerto Rico Water & Power Infrastructure Producer (PRII federation)

`AguaYLuz` is the water/wastewater/power/outage monitoring node of the Puerto
Rico Integrated Intelligence (PRII) federation.

Its federation alias is `aguayluz-pr`. It owns water and wastewater assets,
power generation/grid infrastructure, outage and service-interruption events,
and utility geospatial summaries, exporting them as canonical streams for
downstream correlation in [`thehub-pr`](https://github.com/jotaele44/thehub-pr).
Ownership of the Puerto Rico solid-waste (vertedero/landfill) site registry is
proposed in [`docs/adr/ADR-0004-solid-waste-registry-ownership.md`](docs/adr/ADR-0004-solid-waste-registry-ownership.md).
The registry is populated from EPA sources (see *Real-data status*); its source denominator is
still **OPEN**.

> **Diagnostic-only surface (ADR 0001, Phase 2).** This repo's dashboard is a
> development and diagnostic tool for this producer only. The supported product
> surface for the PRII federation is the hub app
> (`thehub-pr/server/frontend`), which renders this producer's data alongside
> the other engines. See `thehub-pr/docs/adr/0001-federated-engines-single-hub.md`.

## Federation role

| Field | Value |
|---|---|
| Repository | `jotaele44/aguayluz-pr` |
| Federation alias | `aguayluz-pr` |
| Parent hub | [`thehub-pr`](https://github.com/jotaele44/thehub-pr) |
| Primary function | Water/wastewater/power asset registry, outage and service-event monitoring; solid-waste site registry (proposed, ADR-0004) |
| Jurisdiction focus | Puerto Rico |
| Upstream signal source | `centinelas-pr` (news/regulatory signals via `scripts/ingest_news_event.py`) |

## Real-data status

Production status is `PRODUCTION_REAL_DATA_PARTIAL` (`federation.json`): the
corpus is real public data, with some sources external or point-in-time.

- 273 utility assets from public ingests — 39 power generation/substation/
  transmission nodes (`scripts/ingest_power.py`, EIA-860 + OSM derived) and 234
  OSM-derived water/wastewater treatment/pumping/reservoir nodes
  (`scripts/ingest_water.py`, `review_status=needs_review`). Locally imported
  historical hydro registers (`scripts/import_local_hydro_assets.py`) grow
  `data/utility_assets.jsonl` beyond that core.
- PREPS island-wide service events (`scripts/ingest_preps.py`) plus
  per-municipio AEE/LUMA outage incidents (`scripts/ingest_aee.py`, tier
  T2/needs_review point-in-time snapshot).
- PR-region seismic events (`scripts/ingest_usgs_quakes.py`, keyless USGS FDSN
  earthquake feed) into `data/service_events.jsonl`, backing the `SEISMIC_GEO`
  alert module.
- NSF NEON Domain D04 — the four Puerto Rico sites (`CUPE` Río Cupeyes, `GUAN`
  Guánica Forest, `GUIL` Río Yahuecas, `LAJA` Lajas Experimental Station) as
  `NEON_*` assets, plus 328 site×product publication-state rows in
  `data/neon_availability.jsonl` (`scripts/ingest_neon.py`, keyless). Publication
  changes promote to alerts and activate the `TELECOM_SCADA` module. Stream
  discharge / surface-water chemistry readings
  (`scripts/ingest_neon_products.py`) need a NEON token, which this repo does not
  configure — NEON's `/api/v0/data` endpoint returns 403 anonymously, so that step skips
  and exits 0.
  See [`docs/NEON_INTEGRATION.md`](docs/NEON_INTEGRATION.md).
- USGS discrete water-quality samples for the Laguna Cartagena basin
  (`scripts/ingest_usgs_samples.py`, keyless) — 120 results across the lake, its outflow
  and the Lajas well, recovered from the `samples-data` API that replaced the
  decommissioned `nwis/gwlevels` service. The basin has no daily-values record at all;
  see [`docs/LAGUNA_CARTAGENA_GAP.md`](docs/LAGUNA_CARTAGENA_GAP.md).
- USGS discrete groundwater **field measurements**
  (`scripts/ingest_usgs_field_measurements.py`, keyless) — ~6,900 water-level readings
  across 89 `USGSFM_*` wells from the OGC API `field-measurements` collection, the actual
  successor to `nwis/gwlevels`. `scripts/ingest_usgs_groundwater.py` reads Daily Values
  and therefore carries only the 36 PR wells with a continuous series; this adds the 48
  that are visited a few times a year and have no series at all.
- **PRDNER aquifer condition bands** for five south-coast observation wells
  (`scripts/ingest_prdner_well_bands.py`, keyless) — the Optimum / Observation / Operational
  Adjustment / Critical depth-to-water thresholds that a USGS page attributes to PRDNER, read
  from that page's inline JavaScript (tier T2; no effective date is published), frozen with
  the page bytes' SHA-256, and bound by stable id to the existing `USGSGW_` wells. A depth is
  classified against them at read time. Band state is displayed, never alerted on, while the
  readings are provisional; see [`docs/AQUIFER_BANDS_INTEGRATION.md`](docs/AQUIFER_BANDS_INTEGRATION.md).
- USGS **water-use estimates** for 2010, 2015 and 2020 (`scripts/ingest_usgs_water_use.py`,
  keyless, run on demand) — public-supply withdrawals by source, island-wide and for all 78
  municipalities: 601.74 Mgal/d in 2020, of which 536.64 surface water (89.2%) and 65.10
  groundwater (10.8%). 2015 and 2020 are read from USGS data-release tables (tier T1), each
  file pinned by SHA-256; 2010 exists only as a PDF and is a manual transcription bound to
  that PDF's hash (tier T2). These are five-yearly estimates, not current production; see
  [`docs/WATER_USE_INTEGRATION.md`](docs/WATER_USE_INTEGRATION.md).
- **Hydrologic feature inventory: aquifers, wells, springs, surface water, water infrastructure and wetlands**
  (`scripts/ingest_hydro_aquifers.py`, `scripts/ingest_hydro_sites.py`, `scripts/ingest_hydro_names.py`,
  `scripts/ingest_hydro_nhd.py`, `scripts/ingest_hydro_infrastructure.py`, `scripts/ingest_hydro_wetlands.py`,
  `scripts/build_hydro_inventory.py`, keyless, run on demand). Every aquifer and well described by
  USGS (HA 730-N polygons and text, aquifer codes, 5,437 monitoring wells), the Water Quality
  Portal, EPA SDWIS (1,384 wells, no coordinates) and DRNA PIRA 2016, reconciled across sources.
  Claims merge only on a published identifier, name and distance matches stay candidates, so
  counts are ranges (159 aquifer features, range 141–159; 7,321 wells, range 7,240–7,321; 228
  springs; 13,373 NHD stream reaches and 2,508 canal reaches grouped into 324 named watercourses;
  4,949 waterbodies; 806 reservoirs; 1,670 gauges; 835 intakes). Phase 5 adds, from official
  registries only, 36 USACE NID dams, PRASA's public facility layer (a May 2020 snapshot:
  wells, intakes, plants, pump stations, tanks), EPA NPDES wastewater plants, EPA SDWIS treatment
  plants (no coordinates), FEMA/EPA non-PRASA community systems and 7,960 NWI wetlands.
  Source disagreements are kept unresolved. The USGS polygons declare NAD27 but fit the coastline
  only as Puerto Rico 1940, which the ingest re-checks every run. Shown on the Hydro Inventory page
  and as an aquifer filter on Monitoring; see
  [`docs/HYDRO_FEATURE_INVENTORY.md`](docs/HYDRO_FEATURE_INVENTORY.md).
- USGS **annual peak streamflow** (`scripts/ingest_usgs_peaks.py`, keyless) — 8,317 peaks
  across 244 sites, water years **1899–2025**, giving a flood baseline the 14-day and
  1-year windows elsewhere in the corpus cannot supply. The record maximum is
  284,000 ft³/s at Río Grande de Arecibo, 2017-09-20 (María).
- NOAA **NHC** active Atlantic tropical cyclones (`scripts/ingest_nhc_storms.py`, keyless)
  into `data/service_events.jsonl`, filtered to the Puerto Rico approach corridor. Named a
  `WEATHER_HAZARD` primary source in `config/alert_modules.yaml`; its value over the NWS
  feed is lead time — NWS publishes a watch ~48 h out, NHC publishes position and
  intensity from genesis.
- NWS **NWPS river and reservoir gauges** (`scripts/ingest_nwps_gauges.py`, keyless) — observed
  stage and NWS flood category for the 118 Puerto Rico gauges, with action/minor/moderate/major
  thresholds, bound by `usgsId` to the existing `USGS_*` assets. Flood episodes become
  `WEATHER_HAZARD` alerts; the dashboard's **NWS Hydromet** page shows freshness, provenance
  and a refresh control. This is the PR-relevant part of the legacy NWS IDP-GIS catalog; see
  [`docs/NWS_HYDROMET_INTEGRATION.md`](docs/NWS_HYDROMET_INTEGRATION.md) for what else on that
  catalog was and was not wired.
- NWS **Stage IV Puerto Rico rainfall** (`scripts/ingest_stage_iv_pr.py`, keyless) — the daily
  1-, 7- and 30-day radar + gauge rainfall grids NWPS publishes for Puerto Rico, summarised per
  municipio over the HRAP cells inside each Census polygon (with PRISM normal and percent of
  normal). Heavy-rain days (municipio mean ≥ 3 in, or any cell ≥ 6 in) become sub-critical
  `WEATHER_HAZARD` follow-up alerts; the **NWS Hydromet** page lists rainfall by municipio and the
  map has a **Rainfall** municipio fill.
- U.S. Drought Monitor **Puerto Rico native vector footprint + island-wide area statistics**
  (`scripts/ingest_drought_usdm_footprint.py`, keyless) — the date-bound official USDM D0–D4
  GeoJSON components for Puerto Rico plus cumulative "at or above category" percentages. The
  dedicated **Drought Operations** page at `/drought` renders the official weekly footprint,
  municipio boundaries, independent rainfall/gauge/water-asset/outage/alert overlays, per-layer
  freshness, week-over-week history, SHA-256 source provenance and a PNG briefing export. It does
  not interpolate drought boundaries or infer rationing/root cause; missing footprint data is
  shown as unavailable rather than as no drought.
- An **outdoor-conditions layer**: one current-conditions row per municipio in
  `data/outdoor_conditions.jsonl` (`scripts/build_outdoor_conditions.py`), exported to the hub as
  `outdoor_condition` entities. Six sources feed it on the hydromet plane: the NWS San Juan **Surf
  Zone Forecast** (rip current risk, surf height; `scripts/ingest_nws_surf_zone.py`), NWS
  **marine-zone alerts** for PR waters (`scripts/ingest_nws_marine_alerts.py`), the five
  **NDBC/CARICOOS buoys** (`scripts/ingest_ndbc_buoys.py`), the EPA **UV index** per municipio
  (`scripts/ingest_epa_uv.py`), the NWS **gridded heat index** per municipio
  (`scripts/ingest_nws_gridpoint_heat.py`) — all keyless — and **AirNow** air quality
  (`scripts/ingest_airnow.py`), which needs `AIRNOW_API_KEY` and skips without it. It also folds in
  the NWPS, Stage IV, NWS, NHC, USGS quake, DRNA beach and El Yunque data above. Rip current risk
  High and PR marine alerts promote to `WEATHER_HAZARD`. Conditions are context, not safety advice;
  see [`docs/OUTDOOR_CONDITIONS.md`](docs/OUTDOOR_CONDITIONS.md).
- Puerto Rico **solid-waste (landfill) site registry** (`scripts/ingest_solid_waste_registry.py`,
  keyless, run on demand) — the 32 Puerto Rico landfills in EPA's LMOP database, 2024-09 release
  (22 open, 10 closed; coordinates, years opened and closed) as `LANDFILL` entities with a
  `SHUTDOWN` event per closed site, plus 16 EPA ECHO facilities (SIC 4953) held as `needs_review`
  source records. A closure year on an *open* site is a projection and stays in the RAW rows.
  Cross-source matches stay `CANDIDATE_NOT_IDENTITY`, and the result is **OPEN**: no structured
  Puerto Rico solid-waste authority list or unauthorized-dump source has been acquired. EPA
  enforcement context is partial: of the 3,788 Puerto Rico ECHO enforcement cases pulled on
  2026-11-13, the 51 that concern landfills are kept as RAW rows and linked to sites as candidates
  (by name; two by case number in an ECHO facility report), nothing is created from them as an
  entity or event, and the state agency's own records are not covered. ECHO silently ignores its
  `p_naics` filter and its case service drops filters it does not know, so every ECHO query
  carries a filtered-versus-unfiltered control. Accepted sites export as `landfill_site`
  entities. The records are served by `GET /environmental-exposure/entities`, and the
  Environmental Exposure page lists every site read-only (name, kind, municipality, source record,
  opened year, closure, review state). A missing closure reads "No closure recorded" or "Not
  stated by source", never "Open", and a list that disagrees with the graph summary is shown as
  incomplete, with a retry button that reloads the list and the summary together. The list has no
  coordinates yet. See
  [`docs/adr/ADR-0004-solid-waste-registry-ownership.md`](docs/adr/ADR-0004-solid-waste-registry-ownership.md)
  (Proposed).
- Operational alert events (`docs/ALERT_SYSTEM.md`) and the 78-municipio /
  901-barrio geo layer under `data/geo/` (U.S. Census cartographic boundaries).

Advisory/provenance notes live in
`federation.json#federation_readiness_gate.resolved_conditions`; both readiness
booleans are `true` and `blocking_conditions` is empty.

## Run

Commands as declared in `federation.json#hub_callable_commands`:

```bash
python -m pip install uv && uv pip install -e .[dev]   # setup — pulls the shared prii-* packages via the pinned git+https reference in [tool.uv.sources]; no thehub-pr sibling checkout needed
python -m pytest -q                          # test_suite
python scripts/validate_repo.py              # validation gates G01-G08
python3 scripts/federation_export.py --mode test   # export_canonical
```

## Native electricity evidence workspace

The diagnostic app includes a discoverable **Electricity Intelligence** workspace
at `/electricity`, served by `server.backend.app:app`. It exposes separate
observed/reconstructed/forecast/source-candidate views, source receipts, generator
claims, contradiction inspection, guarded EIA workbook acquisition and offline
capture, and English/Spanish controls. Missing source data remain unavailable.
The Evidence inspector also records reversible candidate recommendations with
exact-claim hashes and immutable history. Recommendations preserve every source
claim and contradiction; the shared operator role is disclosed. See the
[review contract and limits](docs/electricity/ADR-0002-candidate-review-ledger.md).
Source acquisition also exposes durable monthly PR research jobs with metadata
and coverage discovery, recoverable page checkpoints, cancellation, retry and
audit export. Complete jobs remain AUDIT ONLY and do not create measurements.
See the [acquisition contract](docs/electricity/ADR-0003-durable-monthly-acquisition.md).
The native plant/generator registry provides literal source identities, temporal
filters, paginated assertion history, overlapping contradictions, source
disclosures and revision-bound exports. Plant references are derived from source
generator plant IDs; they are not independently verified plant records or
cross-source identity matches. See the [registry contract](docs/electricity/ADR-0004-temporal-source-registry.md).

This is an **AUDIT ONLY, NOT CERTIFIED** development tranche. No authoritative
live grid feed, production forecast engine, RC8–RC14 canonical integration or
new Federation-consumer acceptance is claimed. Existing exports and THEHUB's
product role remain intact. See the [architecture](docs/electricity/ADR-0001-native-evidence-workspace.md),
[requirement ledger](docs/electricity/requirements.v1.json) and
[validation/recovery runbook](docs/electricity/OPERATIONS.md).

## Desktop app

Double-click launchers at the repo root start the local desktop app (first run
installs dependencies, later runs work offline):

- `PRII-AGUAYLUZ.command` (macOS) / `PRII-AGUAYLUZ.app`
- `PRII-AGUAYLUZ.bat` (Windows)
- `PRII-AGUAYLUZ.sh` (Linux)

## GIS viewer API

The Map page's GIS tools (layer catalog, identify, search, polygon query and export, saved
views, print, dependency tracing and outage scenarios) are served by `/gis/*`. See
[`docs/GIS_VIEWER_API.md`](docs/GIS_VIEWER_API.md). Dependency results that use
proximity-inferred links are labelled as proxies, and scenarios are always `HYPOTHESIS`.

## Federation contract

`federation.json` is this producer's manifest, conformant to
`thehub-pr/schemas/repo_federation_manifest.schema.json`.
`scripts/federation_export.py` writes
`exports/federation/{sources,entities,relationships,alerts,source_monitors}.jsonl`
plus a `manifest.json` validated against the vendored hub schema
`schemas/federation_export_manifest.schema.json`
(`tests/test_federation_contract_compat.py`).

`source_monitors.jsonl` (thehub-pr ADR 0013) has one row per source in
`config/hydromet_sources.v1.json`, `config/hazard_advisory_sources.v1.json` and
`config/environmental_exposure_sources.v1.json`, with when it last succeeded and
how that is known. For a hydromet source that is its run receipt
(`data/hydromet_receipts.json`) or the latest retrieval in
`data/hydromet_manifestations.jsonl`, whichever is more recent; a hydromet source with
neither (for example AirNow before an API key exists) is reported as not recorded. Every
hazard-advisory and environmental-exposure source is reported as not recorded
(`tests/test_federation_source_monitors.py`).

Every exported row also carries an additive `evidence_state` declaration.
It conforms to thehub-pr's candidate epistemic-state contract, vendored
byte-identically at `schemas/federation_epistemic_state.v1.schema.json`.

Each row declares its epistemic class:

- **CURATED:** records, sources and attribute-derived edges.
- **COMPUTED:** promoter-generated alerts, plant-code duplicates and
  nearest-feed `energized_by` edges. The `energized_by` edges also carry
  `match_basis: spatial_proximity`.

A geometry precision is declared only where the pipeline records how the
point was made:

| Point | Precision |
|---|---|
| Monitoring-location coordinates published by the source | OBSERVED_POINT |
| Polygon or line features | REPRESENTATIVE_POINT |
| Municipio centroids | REPRESENTATIVE_POINT |
| Approximate alert points | REPRESENTATIVE_POINT |

Every other coordinate is left undeclared (the Hub shows it as UNKNOWN).
Tests: `tests/test_federation_evidence_state.py`.

<!-- PROJECT-OPERATING-CONTRACT:START -->
## Current development and certification contract

AguaYLuz is developed as the Puerto Rico utility-infrastructure producer: water, wastewater, power, outages, recovery, hydroelectric, environmental, and spatial/temporal utility evidence. Current development must recompute live source/runtime state rather than treating historical monitoring receipts as current health.

**Operating rules:** preserve raw/normalized/canonical values separately; prefer stable IDs and authoritative bindings over name/proximity heuristics; freeze material source manifestations and SHA-256; close source/retained/excluded arithmetic, schema/null/FK/cardinality gates, GIS validity, temporal validity, contradiction handling, and federation-export lineage. Historical PASS evidence is preserved after downstream failure but does not certify a later runtime manifestation.

**Release discipline:** credential-free feature/data work comes first unless a feature intrinsically requires authentication. Desktop and iPhone are first-class manifestations. PASS means a bounded gate passed; repository certification requires frozen scope/inputs, explicit inclusion/exclusion, validated identifiers, arithmetic closure, positive/negative regression evidence, current rendered QA, and zero material unresolved residue inside the claim.
<!-- PROJECT-OPERATING-CONTRACT:END -->
