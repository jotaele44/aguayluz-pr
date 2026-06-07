# Vectors

`aguayluz-pr` exposes 8 production execution vectors. Each maps to a script,
a CLI subcommand, and a specific Base44 envelope `vector` field. All vectors
have a `--demo-mode` for offline runs and a live mode that hits public APIs.

## Quick reference

| Vector | Script | CLI | Demo input |
|---|---|---|---|
| `AYL_INGEST_PUBLIC_ASSETS` | `ingest_facilities.py` | `aguayluz ingest-frs` | `tests/fixtures/frs/pr_bayamon_npdes.json` |
| `AYL_INGEST_SERVICE_EVENTS` | `ingest_events.py` | `aguayluz ingest-fema` | `tests/fixtures/fema/pr_public_assistance_sample.json` |
| `AYL_BUILD_DEPENDENCY_GRAPH` | `build_dependency_graph.py` | `aguayluz build-graph` | reads `outputs/` |
| `AYL_RECONCILE_PROJECT_STATUS` | `reconcile_status.py` | `aguayluz reconcile` | reads `outputs/` |
| `AYL_DELINEATE_WATERSHEDS` | `delineate_watersheds.py` | `aguayluz delineate` | `tests/fixtures/waters/drainagearea_v3.json` |
| `AYL_TRACK_TIME_SERIES` | `snapshot_run.py` / `diff_runs.py` | `aguayluz snapshot` / `aguayluz diff` | reads `outputs/` |
| `AYL_EMIT_FEDERATION_HANDOFFS` | `emit_federation_handoffs.py` | `aguayluz emit-handoffs` | reads `outputs/` |
| `AYL_EXPORT_CONTROL_PLANE` | (implicit; every vector emits) | `aguayluz export-base44` | reads `outputs/` |

## AYL_INGEST_PUBLIC_ASSETS

**What** — Ingest public registry of utility infrastructure facilities; classify
by name heuristic; snap each to NHDPlus via WATERS.

**Sources** — EPA FRS, HIFLD ArcGIS layers.

**Inputs** — `tests/fixtures/frs/*` or `tests/fixtures/hifld/*` (demo), live
`https://frs-public.epa.gov/...` or HIFLD FeatureServer (live).

**Outputs** — `outputs/utility_assets.json`, plus `review_queue.json` for
records that failed to snap.

**CLI** —
```
# Demo
aguayluz ingest-frs --input tests/fixtures/frs/pr_bayamon_npdes.json --demo-mode
aguayluz ingest-frs --input tests/fixtures/hifld/pr_substations_sample.geojson --source hifld --demo-mode
# Live
aguayluz ingest-frs --live --state PR --city BAYAMON --demo-mode   # FRS + demo WATERS
```

## AYL_INGEST_SERVICE_EVENTS

**What** — Ingest FEMA Public Assistance recovery projects as service events
(no WATERS snap; events are area-bound).

**Sources** — FEMA OpenFEMA v2.

**Outputs** — `outputs/service_events.json`, merged with existing assets.

**CLI** —
```
aguayluz ingest-fema --input tests/fixtures/fema/pr_public_assistance_sample.json
aguayluz ingest-fema --live --state PR --damage-codes D,F --max-records 50
```

## AYL_BUILD_DEPENDENCY_GRAPH

**What** — Typed graph of asset↔asset and event↔asset relationships.

**Edges** — `same_reach`, `same_municipality`, `affects_municipality`,
`shares_disaster`, optional `downstream_of` (WATERS).

**Outputs** — `outputs/dependency_graph.json` + `outputs/bridge_summary.json`.

**CLI** —
```
aguayluz build-graph --demo-mode                       # heuristics only
aguayluz build-graph --use-waters --max-traces 5       # adds live downstream_of
```

## AYL_RECONCILE_PROJECT_STATUS

**What** — Cross-check FEMA project step against asset operational status.
Surfaces 4 finding kinds (`status_mismatch` critical, `stale_asset` warn,
`missing_coverage` warn, `consistent` info). Warn+critical findings populate
the Base44 envelope's `contradictions` field.

**Outputs** — `outputs/reconciliation_report.json`.

**CLI** — `aguayluz reconcile`.

## AYL_DELINEATE_WATERSHEDS

**What** — For each water/wastewater asset, fetch its upstream drainage
area via WATERS `/v3/drainageareadelineation`. Emit area + bounds +
NHDPlusID + headwater COMIDs; GeoJSON sidecar persisted to
`outputs/geometry/`.

**Outputs** — `outputs/watershed_delineation.json` + sidecars.

**CLI** —
```
aguayluz delineate --demo-mode
aguayluz delineate --max-calls 10                       # live, rate-budget-aware
```

## AYL_TRACK_TIME_SERIES

**What** — Snapshot the current entity-output set under
`outputs/history/<run_id>/`. Diff two snapshots to surface adds/removes/
status flips on assets, events, and findings.

**Outputs** — `outputs/history/<run_id>/*.json`, `outputs/run_diff.json`.

**CLI** —
```
aguayluz snapshot --slug after-ingest
# ... another run ...
aguayluz diff                                          # auto-picks last two
aguayluz diff --from <run_id> --to <run_id>           # explicit
```

## AYL_EMIT_FEDERATION_HANDOFFS

**What** — One handoff payload per `linked_modules` entry in
`config/federation_manifest.yaml`. Per-receiver tailoring:
- `moneysweep-pr`: FEMA disaster numbers + dollar fields.
- `spiderweb-pr`: NHDPlus COMIDs + reachcodes + watershed bounds.
- `thehub-pr`: bridge summary + warn/critical contradictions.
- `skywatcher-pr`, `ovnis-pr`: municipality + counts only.

**Outputs** — `outputs/handoff_<target>.json`, Base44 envelope's
`federation_handoffs` pointer list.

**CLI** — `aguayluz emit-handoffs`.

## AYL_EXPORT_CONTROL_PLANE

Every vector implicitly exports `outputs/base44_export.json`. The standalone
`aguayluz export-base44 --run-id <id>` re-builds the envelope from current
entity files without re-running upstream vectors.

## Auxiliary commands

These aren't headline vectors but ship as part of the CLI for development
and operational convenience:

- `aguayluz smoke` — single-asset end-to-end smoke against Lago La Plata
  (`-66.232, 18.388`). Demo mode uses the M2 pointindexing fixture; live
  mode requires `EPA_WATERS_API_KEY`. Writes a one-asset output set so
  G01–G08 flip to PASS — useful as a CI canary.
- `aguayluz build-manifest` — standalone driver for
  `outputs/source_manifest.json`. Re-walks `outputs/utility_assets.json` +
  `service_events.json`, dedupes by `source_ref`. Used after manual edits
  to entity files.

## Full chain

The plan's canonical end-to-end run:

```
aguayluz ingest-frs --input tests/fixtures/frs/pr_bayamon_npdes.json --demo-mode
aguayluz ingest-fema --input tests/fixtures/fema/pr_public_assistance_sample.json
aguayluz build-graph --demo-mode
aguayluz reconcile
aguayluz delineate --demo-mode
aguayluz emit-handoffs
aguayluz snapshot --slug full-run
aguayluz validate-repo
```
