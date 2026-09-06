# Mycelial Phase 1 Ballot A — bounded research ingestion v1

## State

- Certification: **PROVISIONAL** pending exact-head CI and regression execution.
- Capability: `internal_research_ingest_only`.
- Authorization receipt: `governance/mycelial_phase1_research_ingest_authorization_20260906.json`.
- Exact branch base: `3678271a03e36375dc3e9f2fb4da0b6b655622bd` (`main`).
- Prior research-ingest HOLD `4851413154`: preserved as **SUPERSEDED**, not deleted.
- Analytics state: `model_not_calibrated`.

This implementation admits only bounded internal evidence ingestion. It does not authorize ecological calibration, model fitting, prediction, habitat suitability, location ranking, ecological connectivity, production API/GUI exposure, notifications, control actions, or fungal-to-infrastructure inference.

## Scientific identity boundary

Fruiting-body evidence and underground mycelium evidence are separate domains.

A mushroom observation can establish an evidence-backed fruiting occurrence or lifecycle observation under the approved contract. It cannot establish underground network extent, continuity, corridor identity, or shared organism identity from proximity alone.

Environmental variables are retained as evidence-bound context. Correlation does not establish causal identity.

## Manifestation model

Every admitted batch preserves three distinct manifestations:

1. **RAW** — exact UTF-8 JSONL batch bytes, batch SHA-256, exact non-empty raw row text, and row SHA-256.
2. **NORMALIZED** — deterministic structural JSON serialization used for validation and reproducible comparison. Source strings are not linguistically normalized, corrected, or canonicalized by this stage.
3. **CANONICAL** — only schema-valid, semantically valid, dependency-bound research records. Canonicalization does not overwrite conflicting stable IDs; conflicts become immutable rejection events.

RAW, NORMALIZED, and CANONICAL identity are not interchangeable.

## Supported Ballot A record families

The ingest layer consumes the merged Phase 1 v1 design contracts for:

- source/license registry entries;
- provenance records;
- effort-aware survey sessions;
- taxonomic evidence;
- temporal environmental matches;
- environmental evidence sheets;
- stable generalized lifecycle sites;
- visible-fruiting observations;
- media evidence;
- environmental snapshots;
- evidence-bound lifecycle transition assertions.

No deterministic biological state-transition graph is imposed. A transition is accepted only when its evidence endpoints bind to the same site and episode, time is monotonic, and its effective instant lies inside the evidence interval.

## Non-detection rule

A negative survey means **documented non-detection under the stated completed effort**. It is never promoted to ecological absence.

The merged sampling schema requires positive person effort, a completed survey, search geometry without exact coordinates, observer accounting, target scope, substrate/host/deadwood/microsite coverage, equipment, and the invariant phrase:

`documented non-detection under stated effort; not proof of absence`

Incomplete and aborted surveys remain distinct from negatives.

## Coordinate policy

The Phase 1 site contract contains no exact latitude/longitude values. Site location representations are limited to `none`, `generalized`, or `withheld`, with municipality/coarse-grid/withheld precision tiers as permitted by the governing source policy.

Source policies marked `prohibited` or `unknown_hold` fail closed for non-none coordinate representations. Exact coordinates cannot be supplied through a request-controlled disclosure switch.

## Identity and duplicate rules

- `record_type + stable_id + identical canonical payload` => exact replay; no duplicate canonical row.
- `record_type + stable_id + different payload` => conflict rejection; no overwrite.
- Cross-source matching `duplicate_candidate_key` => immutable duplicate-candidate event; assertions remain separate.
- Count equality, name equality, proximity, same category, or deterministic normalization are not identity evidence.

## Order-independence hardening

Source row ordering is not evidence and must not determine admission.

The pipeline therefore executes in two phases:

1. preserve RAW rows and produce schema-valid NORMALIZED manifestations in original source order;
2. canonicalize in deterministic dependency order: source registry → provenance/taxonomy/survey/temporal/environmental definitions → site → observation → media/environmental snapshots → transitions.

Original row order is retained only as a deterministic tie-break inside the same dependency class. A valid site cannot fail merely because its provenance row appeared later in the source file.

## Temporal environmental safeguards

- all compared biological/environmental instants must be timezone-aware;
- lifecycle observations must fall inside their survey interval;
- an `antecedent` environmental observation cannot occur after the biological observation;
- an environmental snapshot must bind to a temporal-match record whose biological instant equals the lifecycle observation instant;
- future-data leakage remains prohibited by the merged design contract;
- no environmental evidence sheet becomes a predictor merely because it exists.

## Persistence and conservation

The SQLite research ledger is append-only. `UPDATE` and `DELETE` are denied for:

- raw batches;
- raw records;
- normalized records;
- canonical records;
- record events;
- ingest receipts.

Receipt arithmetic must close exactly:

`attempted = accepted + rejected + review_queue + exact_replays`

Duplicate-candidate counts are orthogonal relationship counts and therefore are not added to the row denominator.

## Regression gates

The branch test suite adds positive and negative gates for:

- RAW/NORMALIZED/CANONICAL row conservation;
- reversed source-order equivalence;
- append-only mutation denial;
- exact replay idempotency;
- batch-ID digest conflict rejection;
- stable-ID changed-payload rejection;
- invalid negative-survey semantics;
- observer-count mismatch;
- exact-coordinate rejection;
- environmental/biological temporal mismatch;
- cross-source duplicate-candidate preservation without merge;
- non-finite JSON rejection;
- prohibition on promoting `needs_review` lifecycle records into pre-Ballot-B training candidates.

## OPEN residue before any Ballot B calibration

1. Exact-head CI/regression execution has not yet certified this branch.
2. No real Puerto Rico fungal occurrence or repeated-survey dataset is admitted by this implementation alone.
3. Source/license terms must be frozen independently for each biological source before ingestion.
4. Date-matched precipitation, humidity, temperature, soil moisture, substrate/host, canopy, and other candidate predictors require separate evidence sheets and source receipts.
5. Sampling effort and observer-bias denominators must be assembled before any absence-sensitive model.
6. External validation data independent of model fitting remains required.
7. No runtime/API/GUI surface is admitted in this vector.
8. Unexpected engine-level transaction failure currently rolls back the batch; promotion to a persisted failed-receipt mechanism remains an explicit hardening candidate before certification beyond PROVISIONAL.

## Next admission order

1. certify this research-ingest implementation;
2. freeze and admit biological observation sources;
3. assemble stable-site repeated-survey and lifecycle denominators;
4. bind environmental evidence temporally and spatially;
5. freeze the biological training denominator;
6. open a separate Ballot B for known-site fruiting phenology calibration;
7. validate independently before any predictive endpoint is staged.

Island-wide habitat suitability remains downstream of known-site phenology validation.
