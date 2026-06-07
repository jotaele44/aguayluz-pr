# Schemas

12 JSON Schemas, all Draft 2020-12, all `additionalProperties: false`. Every
schema is registered in `src/aguayluz/validation.py:_ENTITY_SCHEMAS` so G01
(`G01_SCHEMA`) validates outputs against them.

## `utility_asset` — the producer's atomic unit

`schemas/utility_asset.schema.json`

A single PR utility infrastructure record. Carries identity (`asset_id`,
`asset_name`), classification (`asset_type`, `asset_subtype`, `operator`,
`municipality`), location (`lat`, `lon`, `geometry_type`), provenance
(`source_ref`, `source_hash`, `evidence_tier`, `confidence`,
`review_status`), and NHDPlus snap output (`comid`, `reachcode`, `measure`,
`vpuid`). The `attribute_coverage` enum (`full`/`partial`) carries the spec's
"no silent substitution" rule for VPU 21.

## `service_event` — area-bound infrastructure event

`schemas/service_event.schema.json`

Outage, restoration, boil-water notice, project update. Always area-bound
(`affected_area`), never point-bound. `notes` is critical: it carries the
FEMA `step=<projectProcessStep>` that M8 reconciliation reads. Dropping
`notes` would silently break stale_asset findings on real data.

## `aguayluz_bridge_summary` — sanitized roll-up for the hub

`schemas/aguayluz_bridge_summary.schema.json`

The federation hub's preferred view of this module's run. Counts, covered
municipalities, narrative risk summary, declared linked_modules, single
confidence + review_status. Built by M7's `build_dependency_graph.py`.

## `base44_export` — the envelope per the skill spec

`schemas/base44_export.schema.json`

Mirrors AGUAYLUZ_PR_SKILL.md lines 250–268 exactly. Status PASS/WARN/FAIL/
BLOCKED. Coverage_pct, records_total, records_review, records_blocked,
confidence_avg. Sanitized summary (no api keys, refused at builder level).
top_findings, contradictions, gaps, next_actions. M15 added
`federation_handoffs` pointer list.

## `source_manifest` — provenance ledger

`schemas/source_manifest.schema.json`

One entry per distinct `source_ref` across the run. Tier + access_date
(required by G02), optional source_hash (sha256), citation, notes.

## `review_queue` — what needs a human

`schemas/review_queue.schema.json`

Severity-tagged items routed out of the main asset/event pipeline. Required
for low-confidence, missing, contradictory, or out-of-bbox records (G04).

## `integration_report` — coverage + gate report per run

`schemas/integration_report.schema.json`

`coverage` block: expected/located/ingested/deduped/unresolved + gaps[]
+ coverage_pct. `gates` array with G01–G08 status (PASS/WARN/FAIL/SKIP).
Drives the Base44 envelope's `status` field and `coverage_pct`.

## `dependency_graph` — M7's typed graph

`schemas/dependency_graph.schema.json`

`nodes`: `{id, kind: asset|event, label, municipality, asset_type, vpuid}`.
`edges`: `{from, to, kind, evidence, weight, confidence}` where `kind` is one
of `same_reach`, `downstream_of`, `upstream_of`, `same_municipality`,
`affects_municipality`, `shares_disaster`. Edges always carry `evidence` so
a reviewer can audit the link without re-deriving it.

## `reconciliation_report` — M8's findings

`schemas/reconciliation_report.schema.json`

`findings` array of `{finding_id, kind, severity, asset_id, event_id,
municipality, details, confidence, fema_step, asset_status}`. `summary`
counts per kind. `finding_id` is a deterministic SHA-1 over a stable seed
so re-runs yield identical IDs.

## `watershed_delineation` — M13's upstream-drainage records

`schemas/watershed_delineation.schema.json`

Array of `{asset_id, nhdplus_id, area_sqkm, headwater_comids,
bounds_bbox, geometry_sidecar, source_ref, source_hash, evidence_tier,
confidence, review_status, attribute_coverage}`. Geometry stays in a sidecar
GeoJSON under `outputs/geometry/` so the entity record stays envelope-sized.

## `run_diff` — M14's snapshot delta

`schemas/run_diff.schema.json`

`assets_added`, `assets_removed`, `assets_changed` (with `{asset_id, field,
from, to}`). Same shape for `events_*` and `findings_*`. `summary.headline`
is the human-readable diff line (e.g. `assets +5/-3/~0`). source_hash and
confidence changes are deliberately filtered out as noise.

## `foia_roster` — M20's public-records request targets

`schemas/foia_roster.schema.json`

Converts producer-observed gaps into structured FOIA request packets. Each
target maps a gap (`review_queue` item / `missing_coverage` finding / VPU 21
partial-coverage asset) to an agency (PRASA/AAA/PREPA/LUMA/FEMA/EPA per
`config/foia_agencies.yaml`), a list of missing fields, a request body the
operator can submit verbatim, and a queued/drafted/sent/fulfilled/denied
status. Deduplicates by `(agency, frozenset(missing_fields))` so two assets
in the same agency missing the same fields merge into one target.

## `hub_packet` — M19's self-contained bundle for thehub-pr

`schemas/hub_packet.schema.json`

Where M15's federation handoffs are file-per-receiver and reference the
producer's outputs/ by path, a `hub_packet` is a single self-contained inline
bundle. Inlines the Base44 envelope, every per-target FederationHandoff, and
the entity records that drive federation decisions. The `signature_sha256`
field is a deterministic hash over the canonical serialization of
`envelope+handoffs+entities` — same inputs always produce the same signature
(content-addressed caching at thehub-pr). Tampering with any inlined field
breaks the signature; `aguayluz.hub_packet.verify_packet_signature()` checks
it on the receiver side.

## `federation_handoff` — M15's per-receiver projection

`schemas/federation_handoff.schema.json`

`target_module_id`, `join_keys` (`key_type` enum: municipality/comid/
reachcode/gnis_id/fema_disaster_number/registry_id), `confidence_floor`,
`time_window`, and a freeform `payload` whose shape varies per receiver. G01
catches handoff_*.json files by prefix-match.

## Adding a new schema (gate-G01 trail)

1. Write `schemas/<name>.schema.json`. `additionalProperties: false`.
2. Add the entity → schema mapping to `_ENTITY_SCHEMAS` in
   `src/aguayluz/validation.py`.
3. Bump the count check in `tests/test_schemas.py`.
4. Write a Pydantic mirror in `src/aguayluz/models.py` if you want
   model-level validation (preferred for entities you construct in-process).
5. Producer scripts call `validate_against_schema(name, instance)` before
   writing.

See `docs/contributing.md` for the full pattern.
