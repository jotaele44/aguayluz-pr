# AguaYLuz-PR Operational Alert System

A permanent, multi-sector operational-alert framework tied to hydro continuity,
infrastructure dependencies, GIS events, and source-preserved evidence. Claude
performs extraction, classification, and schema-constrained generation; **the
AguaYLuz-PR database remains the system of record**.

This is the harmonized build of the *AguaYLuz-PR Alert System Skeleton v0.2*
workbook: it keeps the workbook's operational semantics (10 sector modules,
severity floor `0–5`, `gap_status`, structural covert flags, the VAL-001..010
acceptance rules, the dependency graph, and the MCP tool contract) while
adopting the repo's data idioms (confidence `0–100`, evidence tiers `T1–T4`,
`AYL_` ids, JSON-Schema + Pydantic, and the federation export).

## Modules

Ten sector modules are defined in [`config/alert_modules.yaml`](../config/alert_modules.yaml).
Five sector modules are activated immediately (plus the always-on
`PUBLIC_NOTICE` evidence layer); the rest are seeded dormant and enabled by
relevance.

| Activation | Modules |
|---|---|
| `active` | HYDRO_OPS, POWER_OPS, WEATHER_HAZARD, CONTAMINATION, DAM_SAFETY, PUBLIC_NOTICE |
| `dormant` | TRANSPORT_ACCESS, TELECOM_SCADA, SEISMIC_GEO, INDUSTRIAL |

## Data model

| Artifact | Where |
|---|---|
| Alert event schema | [`schemas/alert_event.schema.json`](../schemas/alert_event.schema.json) |
| Module registry schema | [`schemas/alert_module.schema.json`](../schemas/alert_module.schema.json) |
| Dependency edge schema | [`schemas/alert_dependency_edge.schema.json`](../schemas/alert_dependency_edge.schema.json) |
| Gap log schema | [`schemas/alert_gap.schema.json`](../schemas/alert_gap.schema.json) |
| Pydantic models | [`src/aguayluz/alerts.py`](../src/aguayluz/alerts.py) |
| SQLite/PostGIS DDL | [`schemas/sql/alert_system.sql`](../schemas/sql/alert_system.sql) |
| Seed events / edges / gaps | `data/alert_events.jsonl`, `data/alert_dependency_edges.jsonl`, `data/alert_gaps.jsonl` |

`alert_id` follows `AYL_ALR_<YYYYMMDD>_<slug>`. `severity` is the workbook's
`0–5` operational floor; `confidence` is the repo's `0–100` analyst score. Both
`gap_status` (`none|minor|major|blocking`) and `review_status`
(`accepted|needs_review|rejected|blocked`) are carried so low-confidence or
incomplete records route to review.

## Validation pipeline (VAL-001..010)

[`src/aguayluz/alert_validation.py`](../src/aguayluz/alert_validation.py)
implements the workbook's acceptance rules. JSON Schema owns type/enum/range;
these rules add the cross-field and contextual logic.

| Rule | Scope | Rejects? | Check |
|---|---|---|---|
| VAL-001 | event | yes | `alert_id` unique and non-empty |
| VAL-002 | event | yes | `module_id` exists in the registry |
| VAL-003 | event | yes | `start_at <= end_at` when `end_at` is set |
| VAL-004 | event | yes | `source_ref` or `source_hash` present (no source-less alert) |
| VAL-005 | geo | yes | `latitude`/`longitude` both set or both null |
| VAL-006 | geo | yes | `coord_confidence: exact` requires source-backed coordinates |
| VAL-007 | classification | yes | `event_type` in the controlled vocabulary |
| VAL-008 | dependency | no (advisory) | `asset_id` present before production linking |
| VAL-009 | confidence | yes | confidence ≤ 40 forces a non-`none` `gap_status` |
| VAL-010 | safety | yes | only structural `covert_flags` (no unsupported interpretation) |

## Dependency graph

Directed, evidence-gated edges link infrastructure nodes (e.g. a power node
`energizes` a hydro asset; a hazard area `hydrologically_affects` a reservoir).
Seed edges live in `data/alert_dependency_edges.jsonl`.

## Claude MCP tool contract

[`config/alert_mcp_tools.json`](../config/alert_mcp_tools.json) defines the six
tools (`ingest_alert_source`, `validate_alert`, `upsert_alert`, `link_asset`,
`write_geo_event`, `add_gap`) and the guardrails. `validate_alert` is backed by
the VAL pipeline above; the guardrails restate VAL-004/009/010 plus the
system-of-record rule.

## Data-driven alert generation

The alert layer is no longer seed-only. Two builders project the producer's real,
already-ingested corpus into the alert/dependency layer (run automatically by
`scripts/refresh.py` after ingest, before export):

```bash
# EPA SDWIS boil-water + health-based quality violations -> CONTAMINATION alerts;
# USGS reservoir readings -> HYDRO_OPS reservoir-low alerts (statistical proxy).
python scripts/build_water_alerts.py

# Nearest-power-asset spatial proxy -> water -[energizes]-> power dependency edges
# (closes GAP-003; replaces the null EDGE-POWER-PUMP-SEED placeholder).
python scripts/build_water_power_crosswalk.py
```

Provenance rules the builders honor:

- SDWIS-derived CONTAMINATION alerts inherit the source event's **T1** tier and
  confidence. Only acute (boil-water) and **health-based** quality violations are
  promoted; non-health monitoring/reporting violations stay in the service-event
  stream.
- Reservoir-low alerts are a **statistical proxy** stamped **T2 / needs_review**
  (a reading in the site's own lower percentile), not an official AAA operating
  level. `validation_notes` records the disclaimer and the T1 unblock.
- Crosswalk edges are **proximity inferences** (`evidence_required=true`,
  sub-T1 confidence), not verified circuits.

`aguayluz.water_alerts` holds the pure logic; the pydantic `AlertEvent` model
validates every generated row, and gate G01 re-validates them at export.

## Build & run

```bash
# Build the SQLite DB from the DDL, load seeds+generated rows, run VAL-001..010
python scripts/build_alert_system.py            # writes outputs/alert_system.sqlite + outputs/alert_events.geojson
aguayluz alerts build                            # same, via the CLI
aguayluz alerts validate                         # run VAL-001..010

# Project alerts into the federation `alerts` stream (+ outputs/alert_events.json)
python scripts/federation_export.py --mode test
```

## Federation

`scripts/federation_export.py` projects each alert into the Hub's canonical
`alerts` stream (deterministic `alrt_` id, confidence rescaled to `0–1`,
`location` for spatial joins, `attributes` carrying module/coords/evidence).
The Hub (`thehub-pr`) validates the stream against
`schemas/federation_alert.schema.json`, aggregates it across producers, and
correlates alerts to entities by municipality/location.
