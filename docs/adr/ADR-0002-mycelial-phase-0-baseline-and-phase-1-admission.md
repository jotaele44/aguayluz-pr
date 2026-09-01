# ADR-0002: Freeze the mycelial Phase 0 baseline and require separate Phase 1 admission ballots

- Status: Accepted
- Decision class: Research governance and capability admission
- Baseline repository: `jotaele44/aguayluz-pr`
- Baseline default-branch commit: `a37bf8524524723aea9dedb364e36c5c36643d00`
- Certified source head: `fbc1ba00083350caf2aab93166c2f49e3dc0487d`
- Merged pull request: `#110`
- Supersedes: none

## Decision

AguaYLuz freezes PR #110 as the canonical **Phase 0 research-only fungal-occurrence evidence foundation**. Phase 0 authorizes evidence validation, append-only evidence accounting, provenance, duplicate-candidate review, adjudication, supersession, import receipts, and policy-controlled coordinate withholding.

Phase 0 does **not** authorize ecological calibration, habitat suitability, connectivity output, location ranking, production or GUI admission, public exact sensitive coordinates, notifications, control actions, or fungal-to-infrastructure inference.

Every proposed Phase 1 capability requires its own named human ballot. Approval of one ballot does not imply approval of another. No pre-existing, stacked, legacy, or draft branch is grandfathered by the Phase 0 merge.

## Canonical Phase 0 baseline

The following values are frozen as the Phase 0 baseline. A future change must use a superseding ADR or a versioned amendment approved through a separate governance pull request.

| Baseline field | Canonical value |
|---|---|
| Default-branch commit | `a37bf8524524723aea9dedb364e36c5c36643d00` |
| Certified PR head | `fbc1ba00083350caf2aab93166c2f49e3dc0487d` |
| Evidence schema | `schemas/fungal_occurrence.schema.json` |
| Schema version | `1.1.0` |
| Schema dialect | JSON Schema Draft 2020-12 |
| Evidence object | `FungalOccurrenceRecord` |
| Project namespace | `research.mycelial` |
| Capability classification | `internal_research_only` |
| Tracking reference | `aguayluz-pr#110` |
| Staging feature flag | `AGUAYLUZ_ENABLE_MYCELIAL_RESEARCH_API` |
| Required opt-in value | exactly `1` |
| Staging expiry | `2026-12-31` |
| Default exported-ASGI state | routes disabled |
| Analytics state | HTTP `503`, `model_not_calibrated` |
| Certified test result | `574 passed` |
| Certified coverage | `85.75%` |
| GUI parity | `new=0`, `manifest_issues=0` |
| Desktop certification | Ubuntu, macOS, and Windows passed |

The merge commit did not receive a separate push-triggered workflow wave. The controlling execution evidence is the complete terminal-success matrix on certified source head `fbc1ba00083350caf2aab93166c2f49e3dc0487d`.

## Frozen ledger contracts

Phase 0 defines eight immutable logical ledgers:

1. source records;
2. fungal occurrences;
3. duplicate-candidate links;
4. adjudications;
5. policy decisions;
6. dataset registrations;
7. import receipts;
8. supersessions.

Database triggers deny `UPDATE` and `DELETE` on every ledger table. Corrections are new events, not destructive edits.

The following semantics are frozen:

- exact source-record replay is distinct from cross-source duplicate-candidate matching;
- corroborating records remain separate assertions unless a human adjudication establishes another relationship;
- supersession requires existing predecessor and successor records;
- self-supersession, conflicting linear chains, and cycles fail closed;
- effective-state resolution is deterministic and preserves history;
- occurrence writes, duplicate links, and import receipts are transactional;
- failed or partial imports remain accounted for through immutable receipts;
- invalid schema values and non-finite coordinates cannot be persisted;
- sensitive coordinates are denied unless an occurrence-specific immutable policy decision authorizes the exact disclosure.

## Baseline preservation rules

Changes to any frozen Phase 0 contract require all of the following:

1. a new branch from the exact then-current `main` SHA;
2. one atomic pull request identifying the frozen contract being changed;
3. a versioned schema or migration plan when persistence changes;
4. backward-compatibility and deterministic-replay evidence;
5. human review of scientific, privacy, and operational effects;
6. full final-head recertification;
7. a separate expected-head merge authorization.

A test-count increase, green CI, or a research-only label is not an admission decision.

## Phase 1 scientific data-admission requirements

### 1. Verified occurrence admission

A Phase 1 ingestion proposal must define, before implementation:

- the source and stable source-record identifier;
- acquisition date and content hash;
- license, redistribution, retention, and attribution terms;
- whether exact coordinates may be retained internally and at what access class;
- taxonomic evidence type and reviewer qualification;
- observation timestamp and temporal precision;
- coordinate datum, derivation method, and quantitative uncertainty;
- evidence tier and review state mapping;
- exact replay identity and duplicate-candidate identity;
- correction, retraction, and supersession behavior;
- complete/partial/failed receipt accounting.

Records lacking required provenance must be rejected or retained only in an explicitly non-admitted review queue. Missing values must remain missing; they may not be filled with assumed coordinates, dates, taxa, effort, or environmental values.

### 2. Sampling-effort representation

Presence records alone are insufficient for calibration or absence inference. Survey data must record, where applicable:

- survey protocol and protocol version;
- survey start and end time;
- searched area, route, plot, transect, or bounded search geometry;
- completed person-minutes or equivalent effort measure;
- observer count and observer identifiers or controlled pseudonyms;
- observer expertise or qualification class;
- target taxon or guild;
- substrate, host, deadwood, and microsite coverage;
- weather and visibility constraints;
- equipment used;
- positive, negative, incomplete, or aborted outcome;
- reason an incomplete or aborted survey was not treated as a negative survey.

A negative survey is evidence of non-detection under a documented protocol. It is not proof of absence.

### 3. Taxonomic evidence

Taxonomic assertions must distinguish at least:

- specimen or voucher verified;
- expert verified;
- photo or media supported;
- reported without independent verification;
- unresolved or unknown.

Where relevant, records must preserve voucher or collection identifiers, media hashes, determiner identity, determination date, taxonomic authority/version, synonym resolution, and the evidence supporting species-, genus-, guild-, or morphotype-level identification.

Taxonomic confidence may not be inferred from source popularity, record volume, map precision, or model score.

### 4. Temporal matching

Environmental predictors must be temporally aligned to the biological observation or survey. Each proposed predictor must specify:

- observation timezone and normalization rule;
- source observation or acquisition time;
- aggregation window;
- lag and lead windows;
- publication or processing latency;
- missing-period behavior;
- whether the value is contemporaneous, antecedent, climatological, or static;
- safeguards against future-data leakage.

Calendar-date matching alone is insufficient when acquisition times, timezone boundaries, or ecological lag windows matter.

### 5. Environmental predictor admission

Each predictor requires an evidence sheet containing:

- scientific rationale and intended causal or correlational interpretation;
- source authority and product version;
- units, scale, resolution, CRS, datum, and spatial support;
- Puerto Rico coverage and known gaps;
- temporal cadence and latency;
- processing, resampling, interpolation, or derivation steps;
- uncertainty and quality flags;
- missing-data behavior;
- licensing and redistribution constraints;
- content hashes or reproducible acquisition receipts;
- test fixtures containing positive, missing, stale, and contradictory cases.

Predictors may not be admitted merely because they are available. Invented weights, undocumented transformations, and silent imputation are prohibited.

### 6. External validation

No calibrated ecological output may be admitted without data independent of model fitting and threshold selection.

The validation plan must pre-register:

- the unit of independence: site, survey, observer, municipality, time block, or another defensible grouping;
- holdout construction and leakage controls;
- target metrics and uncertainty intervals;
- calibration and discrimination evaluation;
- class-imbalance treatment;
- spatial and temporal transfer tests;
- failure thresholds and rollback conditions;
- reporting of negative, null, and contradictory results;
- a prohibition on selecting the best-performing holdout after results are known.

A single random row split is not sufficient when records from the same site, observer, survey, or time window can appear in both training and validation sets.

## Separate Phase 1 ballots

Every ballot must be recorded independently. The allowed decisions are:

- `REJECT` — the capability may not proceed;
- `HOLD` — requirements remain incomplete;
- `APPROVE_DESIGN_ONLY` — schemas, fixtures, and documentation may be prepared, but no data or runtime capability may be admitted;
- `APPROVE_RESEARCH_INGEST` — bounded internal ingestion may proceed under the approved contract;
- `APPROVE_RESEARCH_EXECUTION` — bounded research computation may proceed, but no production or public output is admitted;
- `APPROVE_STAGED_RUNTIME` — an internal feature-gated surface may be prepared with classification, tracking, expiry, parity accounting, and fail-closed defaults;
- `APPROVE_PRODUCTION_ADMISSION` — requires a distinct production ballot and is not available by implication from any research approval.

### Ballot A — Data ingestion and lifecycle evidence

Scope:

- verified occurrences;
- stable sites or survey locations;
- repeated survey sessions;
- visible fruiting lifecycle observations;
- media evidence;
- environmental snapshots tied to observations;
- append-only lifecycle transitions.

Minimum approval evidence:

- source/license registry;
- versioned schemas;
- complete provenance and receipts;
- effort-aware negative-survey contract;
- taxonomic-evidence contract;
- coordinate-redaction policy;
- correction, retraction, duplicate, and supersession behavior;
- bounded import accounting and rollback tests.

Approval of Ballot A does not authorize calibration, connectivity, a GUI, a public API, or a persistent runtime service.

### Ballot B — Ecological calibration

Scope:

- fitted parameters;
- habitat suitability or occurrence probability;
- threshold selection;
- uncertainty estimates;
- taxon- or guild-specific models.

Minimum approval evidence:

- admitted Ballot A data;
- documented sampling effort and bias controls;
- pre-registered training and validation design;
- independent external validation;
- model card and predictor evidence sheets;
- reproducible seeds, environments, inputs, and receipts;
- explicit failure thresholds and rollback plan;
- proof that outputs cannot become collection or precise-location rankings.

Until approved, all analytics must continue to return HTTP `503` and `model_not_calibrated`.

### Ballot C — Connectivity research

Scope:

- ecological resistance surfaces;
- movement, dispersal, or continuity hypotheses;
- graph, least-cost, circuit, or corridor analyses.

Minimum approval evidence:

- a named biological mechanism and taxonomic scope;
- peer-reviewed or otherwise reviewed parameter basis;
- admitted calibrated inputs or a clearly labeled exploratory design;
- sensitivity analysis across plausible parameters;
- null models and artifact rejection;
- independent validation plan;
- explicit prohibition on interpreting ecological connectivity as tunnels, pipelines, vents, military facilities, anomalous corridors, or concealed infrastructure.

Connectivity output remains prohibited until this ballot is approved separately from calibration.

### Ballot D — Sensitive-taxon and coordinate policy

Scope:

- which taxa, sites, records, and precision levels are sensitive;
- internal retention and role-based access;
- public generalization, withholding, and delayed release;
- audit and revocation behavior.

Minimum approval evidence:

- policy authority and reviewer identities;
- occurrence-specific or rule-specific decision semantics;
- precision tiers and generalization methods;
- disclosure logging;
- revocation and supersession procedures;
- tests proving no request-controlled boolean can expose coordinates;
- tests proving exported, logged, cached, and error responses remain redacted.

Approval of ingestion does not authorize exact-coordinate disclosure.

### Ballot E — Runtime, API, or GUI surface

Scope:

- any persistent ASGI route;
- any dashboard or field console;
- any operator-facing workflow;
- any background job, scheduler, notification, export, or federation surface.

Minimum approval evidence:

- approved underlying data or computation ballot;
- capability classification;
- named feature flag with exact opt-in semantics;
- tracking reference and expiry date;
- independent application boundary or approved canonical-app integration;
- authentication and authorization model;
- rate, resource, and failure controls;
- GUI capability manifest entry when human-facing;
- visible navigation and full backend-to-GUI binding when production-facing;
- end-to-end reachability and negative-access tests;
- rollback and expiry behavior.

A console or route may not be justified solely as a demonstration of schemas or research code.

## Atomic implementation protocol

For each approved ballot capability:

1. create a new branch from the exact current `main` SHA;
2. name the ballot and approval receipt in the branch and PR body;
3. implement one atomic capability boundary;
4. avoid stacking on an unmerged or deleted source branch;
5. avoid combining data ingestion, calibration, connectivity, sensitive-coordinate policy, and runtime admission in one PR;
6. keep the PR draft until human review authorizes ready-for-review;
7. run all required repository workflows on the final exact head;
8. reconcile the branch with then-current `main` without force-pushing;
9. require a separate expected-head merge authorization;
10. preserve all unapproved capabilities as unreachable and fail closed.

The required certification matrix includes, as applicable:

- Python 3.10 and 3.12;
- Ruff and repository validation gates;
- schema positive and negative fixtures;
- append-only attack tests;
- duplicate, replay, receipt, and supersession tests;
- data-accounting and determinism tests;
- GUI parity and browser reachability when a human surface exists;
- CodeQL, Secret scan, pip-audit, and federation drift;
- Ubuntu, macOS, and Windows desktop build and packaging.

## Disposition of existing Phase 1 work

PR #111 is an existing draft containing multiple Ballot A and Ballot E concerns in one branch, including lifecycle evidence, survey ingestion, environmental snapshots, a console, and runtime endpoints.

This ADR does not approve PR #111. Before admission, it must be reviewed against the ballots above and must either:

- be decomposed into separately reviewable atomic PRs; or
- demonstrate, through an explicit human ballot, why its combined scope is necessary and how each capability remains independently gated.

Its current draft state must be preserved. Green CI, inherited Phase 0 history, or a fail-closed prediction endpoint does not substitute for an admission ballot.

Legacy or open mycelial PRs created before this baseline likewise receive no inherited authority. Their code, schemas, data, and claims must be reconciled against this ADR before reuse.

## Consequences

- Phase 0 remains stable and evidence-focused.
- Data ingestion can advance without silently authorizing ecological models.
- Calibration cannot silently authorize connectivity or location ranking.
- Sensitive-coordinate policy is adjudicated independently from data collection.
- Runtime and GUI exposure require explicit operational admission.
- Pre-existing Phase 1 work remains reviewable but cannot bypass the new governance boundary.
- Scientific gaps remain visible rather than being hidden by software completeness or green CI.

## Preserved prohibitions

The following remain prohibited unless separately and explicitly approved where an approval path exists:

- production or GUI admission;
- calibrated analytics;
- habitat suitability output;
- location ranking;
- ecological connectivity output;
- public exact sensitive coordinates;
- fungal-to-infrastructure inference;
- notifications;
- automated control actions.
