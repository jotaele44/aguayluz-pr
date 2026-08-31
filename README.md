# AguaYLuz — Puerto Rico Water & Power Infrastructure Producer (PRII federation)

`AguaYLuz` is the water/wastewater/power/outage monitoring node of the Puerto
Rico Integrated Intelligence (PRII) federation.

Its federation alias is `aguayluz-pr`. It owns water and wastewater assets,
power generation/grid infrastructure, outage and service-interruption events,
and utility geospatial summaries, exporting them as canonical streams for
downstream correlation in [`thehub-pr`](https://github.com/jotaele44/thehub-pr).

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
| Primary function | Water/wastewater/power asset registry, outage and service-event monitoring |
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
  (`scripts/ingest_neon_products.py`) need `NEON_API_TOKEN` — NEON's `/api/v0/data`
  endpoint returns 403 anonymously, so that step skips and exits 0 without one.
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
- USGS **annual peak streamflow** (`scripts/ingest_usgs_peaks.py`, keyless) — 8,317 peaks
  across 244 sites, water years **1899–2025**, giving a flood baseline the 14-day and
  1-year windows elsewhere in the corpus cannot supply. The record maximum is
  284,000 ft³/s at Río Grande de Arecibo, 2017-09-20 (María).
- NOAA **NHC** active Atlantic tropical cyclones (`scripts/ingest_nhc_storms.py`, keyless)
  into `data/service_events.jsonl`, filtered to the Puerto Rico approach corridor. Named a
  `WEATHER_HAZARD` primary source in `config/alert_modules.yaml`; its value over the NWS
  feed is lead time — NWS publishes a watch ~48 h out, NHC publishes position and
  intensity from genesis.
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

## Desktop app

Double-click launchers at the repo root start the local desktop app (first run
installs dependencies, later runs work offline):

- `PRII-AGUAYLUZ.command` (macOS) / `PRII-AGUAYLUZ.app`
- `PRII-AGUAYLUZ.bat` (Windows)
- `PRII-AGUAYLUZ.sh` (Linux)

## Federation contract

`federation.json` is this producer's manifest, conformant to
`thehub-pr/schemas/repo_federation_manifest.schema.json`.
`scripts/federation_export.py` writes
`exports/federation/{sources,entities,relationships,alerts}.jsonl` plus a
`manifest.json` validated against the vendored hub schema
`schemas/federation_export_manifest.schema.json`
(`tests/test_federation_contract_compat.py`).

## Bounded real-data partial export

`tools/build_real_data_partial_export.py` builds a deterministic package from
committed real/public-derived data without network access or credentials. The
package is explicitly `PRODUCTION_REAL_DATA_PARTIAL`; it is not a Puerto
Rico-wide completeness claim.

The output contains whole-row `utility_assets.jsonl` and
`outage_events.jsonl`, a `recovery_projects.jsonl` stream that may validly be
empty when no canonical project corpus exists, evidence-gated
`continuity_risk_edges.jsonl`, and a manifest with source and output hashes,
counts, limitations, and caveats.

```bash
python tools/build_real_data_partial_export.py \
  --generated-at 2026-08-17T01:15:00Z \
  --out /tmp/aguayluz-real-data-partial
python -m pytest -q tests/test_real_data_partial_export.py tests/test_schemas.py
```

Recurring access semantics are frozen in
`registry/utility_source_registry.v1.json`; continuity semantics are frozen in
`config/continuity_risk_taxonomy.v1.json`. `EDGE-WP-*` relationships remain
spatial discovery proxies, never feeder or circuit identity. Explicit source
fuel tokens create only fuel-sensitive candidates and prove neither current
stock, supplier, delivery route, nor outage cause. EPA WATERS/NHDPlus evidence
remains `PROVISIONAL_PARTIAL` and bounded to VPU-21; off-network and
no-waterbody outcomes are not extrapolated to Puerto Rico-wide coverage.
