# AguaYLuz infrastructure ontology v0.1

Status: **PROVISIONAL / INTERNAL PREFLIGHT**

This release begins a non-destructive migration from the legacy flat
`utility_asset` representation to a versioned infrastructure ontology. It does
not change the production `utility_asset.schema.json` contract and does not
rewrite `data/utility_assets.jsonl`.

## Why this exists

The legacy contract uses `asset_type` as a broad sector and leaves
`asset_subtype` unconstrained. That was sufficient for early federation and map
work, but it cannot safely distinguish sites, physical assets, components,
linear infrastructure, monitoring locations, or regional terminology.

The ontology therefore separates classification from identity and preserves the
legacy record as a source manifestation.

## Core invariants

- Raw source strings are immutable evidence; normalization is comparison-only.
- A canonical classification is not proof that two source records describe the
  same physical object.
- `site`, `asset`, `component`, `linear_asset`, and `observation_point` are
  distinct feature kinds.
- Projects and permits are evidence about assets, not automatically physical
  assets themselves.
- Alias matching, normalized-name equality, count equality, proximity, or source
  absence cannot independently prove asset identity.
- Unknown or ambiguous legacy labels remain `unresolved` rather than being
  mapped to the nearest known type.
- PR-wide exhaustion is not claimed by this release. Audit statements are
  bounded to the exact `utility_assets.jsonl` snapshot supplied to the audit.

## EBAS decision

Puerto Rico's `EBAS` terminology is represented as a **regional term / alias**
for the canonical type `sanitary_sewer_pump_station`.

This prevents double counting where one source says `EBAS`, another says
`wastewater pump station`, and another says `lift station`.

The alias has `identity_effect = none`: it supports classification vocabulary
but cannot by itself establish that two records are the same station.

A station's wet well, pumps, generator, controls, SCADA equipment, and connected
force main are separate components or related assets when source evidence
supports that decomposition.

## Current artifacts

- `ontology/infrastructure_terms.v0.1.json`
  - versioned canonical term registry
  - feature kinds and domains
  - Puerto Rico aliases, including EBAS
  - conservative legacy crosswalk
- `schemas/infrastructure_classification.schema.json`
  - schema for source-to-ontology classification decisions
- `ontology/tools/audit_infrastructure_vocabulary.py`
  - read-only denominator and classification audit
- `tests/test_infrastructure_ontology.py`
  - positive, negative, conservation, and ambiguity regression gates
- `.github/workflows/infrastructure-ontology-audit.yml`
  - reproducible CI audit and hashed artifact bundle

## Legacy crosswalk policy

The v0.1 crosswalk deliberately contains unresolved entries.

Examples:

- legacy `water + pump_station` is unresolved because the legacy pair cannot
  distinguish raw-water, potable distribution, booster, well, or other pumping
  functions;
- legacy `water + pipeline` is unresolved because transmission, distribution,
  conduit, and other line functions are not recoverable from that pair alone;
- legacy `water + intake_outfall` is unresolved because the label combines
  opposite network roles;
- legacy `wastewater + wastewater_asset` remains unresolved because the subtype
  is an umbrella bucket rather than a physical type.

These are expected preflight findings, not audit failures.

## Audit arithmetic

For a frozen input snapshot, the audit requires:

`source_rows = classified + unresolved + excluded + superseded`

The raw `(asset_type, asset_subtype)` pair counts must also sum exactly to the
source row count. Any unexplained mismatch fails closed.

The audit records SHA-256 hashes for the source asset snapshot, ontology
registry, classification output, and report.

The historical 8,475-row input is frozen at
`ontology/snapshots/utility_assets.8475.jsonl.gz`; its manifest binds the source
commit, row count, byte sizes, and compressed and uncompressed SHA-256 values.
Current `data/utility_assets.jsonl` is intentionally not substituted when it
drifts. Current-main rows outside that snapshot require a separate audit and do
not inherit this bounded replay's classifications.

## Migration sequence

1. Freeze and audit the current raw vocabulary.
2. Adjudicate every raw pair with source-aware evidence.
3. Keep unresolved residue explicit.
4. Add canonical site / asset / component / linear-asset schemas.
5. Add source-manifestation and source-assertion models.
6. Add typed relationship, geometry-manifestation, lifecycle, measurement, and
   owner/operator role models.
7. Generate a legacy compatibility projection from the new model.
8. Migrate one bounded asset family vertically, beginning with wastewater pump
   stations / EBAS.
9. Only after conservation, regression, and federation gates pass should the
   canonical model become the source of truth.

## Certification boundary

`PASS` for the ontology registry means its internal structural invariants pass.
It does **not** mean the Puerto Rico infrastructure universe is complete.

A facility-type denominator can be certified only after its included source
universes, duplicates, unresolved candidates, temporal coverage, and exclusion
rules are explicit and arithmetic closes with zero unresolved residue inside the
claim.
