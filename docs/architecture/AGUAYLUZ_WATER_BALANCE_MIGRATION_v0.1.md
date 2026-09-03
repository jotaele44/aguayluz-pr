# AguaYLuz Water-Balance Migration and Backward-Compatibility Plan v0.1

Status: **Design only**  
Pinned base: `main@17c843595b5cdfbcef4e5f7b1ac6c662092e335d`

## Invariants

The migration must preserve all existing source records, identifiers, event histories, alert histories, source hashes, review states, GUI routes, federation outputs, and scheduled refresh behavior until a separately approved implementation phase proves parity.

No phase may silently rewrite `data/*.jsonl`, activate network polling, add database writes, enable notifications, change incident truth, expose restricted topology, or delete a legacy schema.

## Phase 0 — Design freeze

Deliverables in this PR:

- architecture definition;
- component inventory and compatibility matrix;
- canonical schema contracts;
- nested balance contract;
- machine-readable migration inventory;
- representative fixture suite;
- schema/fixture contract tests.

Exit criteria:

- all new JSON schemas pass Draft 2020-12 schema checks;
- fixture taxonomy covers positive, negative, missing, stale, contradictory, double-counted, meter-reset, time-skew, unit-error, and underdetermined cases;
- no runtime, exporter, GUI, scheduler, data, or workflow behavior changes;
- PR remains draft.

## Phase 1 — Identity and semantics crosswalk

Create append-only mappings from existing source records to canonical concepts.

Required outputs:

- `source_asset_id -> canonical_asset_id` mappings;
- `monitoring_reading.metric -> phenomenon` mappings;
- source unit and datum registry;
- provider/adapter/source-record equivalence groups;
- unresolved and contradictory mapping ledger;
- exact mapping receipts with input and output hashes.

Controls:

- no coordinate-only asset merges;
- no dependency edge promoted to hydraulic flow without evidence;
- no source records modified;
- unmapped concepts remain explicit gaps.

## Phase 2 — Shadow projection

Add a disabled, offline projection command that reads existing JSONL records and emits canonical water-balance records to an ignored or temporary output path.

Controls:

- opt-in command only;
- no default refresh-plan registration;
- no database writes;
- no changes to existing generated data;
- deterministic output and content hashes;
- one projection receipt per input file;
- exact source-record lineage on every projected record.

Exit criteria:

- byte-identical reruns;
- zero orphan canonical references;
- zero unclassified units or datums in the pilot slice;
- all exclusions reported.

## Phase 3 — Dual-read validation

Compare legacy analytical outputs with canonical projections without changing the public API.

Required comparisons:

- asset counts and identifier coverage;
- observation counts by provider, metric, interval, and review status;
- alert-input eligibility;
- freshness and provisional-state parity;
- source and evidence lineage parity;
- contradiction and gap counts.

Any divergence must be classified as intended normalization, newly exposed gap, legacy defect, or projection defect.

## Phase 4 — Bounded pilot topology

Select one hydrologic system with the highest available telemetry coverage. Candidate systems must be scored on:

- rainfall and watershed coverage;
- reservoir stage and stage-storage curve availability;
- measured inflow and release coverage;
- treatment intake and finished-water output;
- tank and transmission telemetry;
- pressure-zone or district-meter coverage;
- groundwater and well-withdrawal coverage;
- operator data-sharing and disclosure constraints.

The pilot topology is read-only and may include unresolved edges. An unresolved edge cannot carry a formal balance term.

## Phase 5 — Shadow nested balance engine

Implement the six balance types with no alert or incident activation.

Required behavior:

- explicit boundary and interval;
- normalized quantity and source unit;
- uncertainty propagation;
- freshness and quality gates;
- missing-term and underdetermined states;
- double-count detection;
- first-failed-boundary localization;
- model residual classified separately from measured loss;
- deterministic assessment receipts.

Every assessment must include the exact eligible and excluded term IDs.

## Phase 6 — Read-only API and GUI

Only after shadow validation may a separate PR add discoverable read-only surfaces.

Required surfaces:

- balance coverage summary;
- boundary and interval selection;
- inputs, outputs, storage change, residual, and uncertainty envelope;
- excluded and stale terms;
- contradiction review;
- first-failed-boundary view;
- cause-attribution candidates with explicit non-proof language;
- provenance and transformation lineage.

Public views must generalize or redact restricted topology.

## Phase 7 — Alert and incident integration ballot

A balance assessment may become an alert candidate only after a separate policy defines magnitude, persistence, coverage, corroboration, and human-review thresholds.

A balance assessment cannot directly create a confirmed water-disruption incident. It must pass through the existing candidate validation, truth-strength, and lifecycle system.

## Phase 8 — Federation export ballot

Water-balance records remain denied from federation export until:

- schemas are stable and versioned;
- disclosure policy is approved;
- receiving modules accept the entity types;
- export tests prove no restricted topology or source leakage;
- legacy export counts and hashes remain stable;
- rollback is documented.

## Backward compatibility

### Existing schemas

Existing schema files remain valid and authoritative for their current records. New canonical records use the versioned `schemas/water-balance/v0.1/` namespace.

### Existing data

Existing JSONL files are never rewritten by projection. Future canonical records must be emitted to separate files or storage tables.

### Existing APIs

No existing route changes response shape. Future balance APIs use a new read-only namespace.

### Existing GUI

No existing page is repurposed. Future balance views are additive and manifest-mapped.

### Existing alerts and incidents

No historical or current alert/incident state is recalculated merely because a balance model is introduced.

### Existing federation exports

No new entity type is exported without an explicit compatibility ballot.

## Rollback requirements

Every implementation phase must be removable by disabling the new feature flag or deleting derived outputs. Because source records are immutable and canonical projection is additive, rollback must not require restoring modified source data.

Required receipts:

- base and head SHA;
- configuration hash;
- source file hashes and row counts;
- output hashes and row counts;
- mapping and exclusion counts;
- test and validation results;
- activation state;
- rollback command or procedure.

## Open-PR coordination

Before Phase 1 implementation:

1. adjudicate #109 versus #116 USGS overlap;
2. decide whether #101 is the canonical asset identity/topology base;
3. determine whether #118 becomes the pilot control-plane input;
4. keep #114/#115 karst relations contextual unless direct hydrologic evidence exists;
5. examine #104-#108 only for unique, still-valid patches;
6. re-resolve current `main` and abort on overlapping architecture drift.

## Promotion policy

Each phase requires its own PR and approval. Completion of this design PR authorizes no implementation, merge, live execution, or production promotion.