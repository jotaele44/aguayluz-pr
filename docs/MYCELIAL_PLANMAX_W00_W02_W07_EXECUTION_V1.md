# Mycelial Plan Max — W00/W01/W02/W07 execution package v1

Status: **DRAFT / DESIGN + DISCOVERY ONLY**  
Exact base: `eb6fa76514257f1361b7ceb7ff298bb4f11161e9`  
Governing ADR: `docs/adr/ADR-0002-mycelial-phase-0-baseline-and-phase-1-admission.md`

This package advances the non-predictive prerequisites for genuine known-site mushroom phenology research. It does not ingest real biological records, fit models, expose a runtime, authorize exact sensitive-coordinate disclosure, or merge the independent ingestion PR.

## 1. W00 — baseline, scope, and authority

### Frozen repository states

- Current `main` at branch creation: `eb6fa76514257f1361b7ceb7ff298bb4f11161e9`.
- Existing bounded research-ingest PR: `#238`.
- PR #238 exact head at execution start: `7f7fa5f9826604c2d47e04267bb6cd6c76fc97fb`.
- PR #238 remains an independent predecessor and is not rebased or modified by this package.
- The 2026-09-09 source audit remains an audit artifact, not an original biological source archive.

### Scientific invariants

1. Acquire observations before calibration; calibrate before prediction.
2. Known-site phenology is the first modeling target. Island-wide habitat suitability remains downstream.
3. Fruiting-body evidence does not establish underground mycelial extent or continuity.
4. Source manifestation identity does not establish biological identity.
5. Non-detection requires documented survey effort and is not proof of absence.
6. Environmental correlation does not establish a causal biological mechanism.
7. RAW, NORMALIZED, and CANONICAL representations remain distinguishable.
8. Contradictions and duplicate candidates remain visible until adjudicated.
9. Sensitive or unresolved coordinates fail closed.
10. Unresolved license, identity, arithmetic, or certification evidence cannot be promoted by convenience.

### First forecast claim, still NOT authorized

The preferred future modeling target is:

> Probability of detecting a named mushroom taxon or defensible guild at an already monitored site during the next prescheduled survey, under a documented search protocol.

This package defines evidence needed to make that future target testable. It does not calculate that probability.

## 2. W01 — rights, privacy, and retention contract

The source registry is frozen in `docs/mycelial/source_contracts/planmax_v1.json`.

Rights are action-specific. For every source manifestation independently record whether the project may:

- acquire the public representation;
- retain original bytes;
- normalize fields;
- create derived analytical data;
- use data in research modeling;
- redistribute source records;
- redistribute or transform media;
- retain location information and at which access class;
- publish generalized occurrence information.

A successful HTTP request is not a license decision. A provider-level license is not automatically a media license. A portal-wide policy is not automatically the same as an individual collection's terms.

### Coordinate boundary

This W07 contract contains no latitude/longitude fields. Valid sites use only `generalized` or `withheld` location modes. Sensitive and sensitivity-unresolved sites must use `withheld` mode.

Do not request, recover, derive, log, cache, export, or expose private/obscured exact coordinates through this package. A future internal exact-coordinate retention design, if needed, belongs to the separately governed sensitive-coordinate ballot and must not be implied by ingestion approval.

## 3. W02 — source contracts and access diagnostics

### Preferred acquisition hierarchy

1. Authoritative provider-native export or API manifestation.
2. Provider-registered Darwin Core Archive and native metadata.
3. GBIF dataset/download manifestation when independently bound to the provider dataset.
4. Aggregator discovery results only as discovery evidence until the exact underlying manifestation is frozen.

A mirror or transformation may be useful, but its bytes and identifiers remain its own source manifestation.

### Current bounded source states

- iNaturalist: supported API documentation and per-record observation/media licensing confirmed as design constraints. Substantial acquisition should use supported datasets/exports where appropriate; application API use must remain bounded by official rate guidance.
- GBIF: occurrence search is paginated and bounded; large/exhaustive retrieval uses the authenticated asynchronous download service. `kingdomKey=5` identifies Fungi in the GBIF backbone, but a Fungi filter is not a mushroom-only forecast denominator.
- MyCoPortal: use as a collection-discovery and provider-specific archive plane. Generic portal usage guidance and collection-specific terms remain separate evidence.
- CUP: candidate archive-acquisition pilot. GBIF dataset manifestation `5a6538b8-e35c-46c4-8978-6858a657a75f` has a CC0 declaration and points to a CUP Darwin Core Archive endpoint. Direct binary retrieval still failed in the tested execution environment; no archive hash or row count is therefore claimed.
- BPI: provider/dataset binding exists; current exact rights manifestation remains subject to re-verification before admission.
- ILL: current license/metadata unresolved; HOLD.
- NY: a 2021 portal snapshot is not a current denominator simply because its profile is retrieved today.
- PUR: a 2021 snapshot exposes a CC BY-ND badge, but exact license version/scope remains unresolved; derivative admission remains HOLD.
- UPRRP/MAPR: institutional fungal holdings are scientifically important, but their current online fungal denominator/export/license state remains unresolved or partial.
- Mushroom Observer: direct-source contract remains to be frozen before using a portal mirror as authoritative.

### Required acquisition receipt

No original payload is considered acquired until a receipt records, at minimum:

- provider and dataset identity;
- source endpoint or export job identity;
- exact query/filter or archive version when applicable;
- retrieval window;
- HTTP/export status and redirects when available;
- media/content type;
- byte count;
- SHA-256 of original received bytes;
- native metadata or EML binding when supplied;
- terms/rights evidence state;
- coordinate retention class;
- failure or partial-acquisition disposition.

Parsed HTML, analyst transcription, a URL, a file name, or a copied subset is not original-source-byte evidence.

### Acquisition failure taxonomy

Classify failures separately as applicable:

`DNS | TLS | HTTP | AUTHENTICATION | RATE_LIMIT | ACCESS_POLICY | CONTENT_TYPE | TRUNCATION | ARCHIVE_STRUCTURE | METADATA_BINDING | LICENSE_HOLD | COORDINATE_POLICY_HOLD | UNKNOWN`

Do not infer that a source is offline from one failed route. Do not retry indefinitely without a reason to expect a different outcome.

## 4. Identity and accounting rules before any filtering

Preserve independently:

`PROVIDER → DATASET → SOURCE_RECORD → SPECIMEN/MATERIAL → COLLECTING_EVENT → SITE → SURVEY → FRUITING_EPISODE → FRUITING_BODY → MEDIA`

Not every source supports every level.

For a proposed equivalence between two representations, retain candidate relationships and calculate set operations only at the declared identity level:

- `INTERSECTION`
- `A_ONLY`
- `B_ONLY`
- `UNION`
- `SYMMETRIC_DIFFERENCE`

Name/date/taxon/proximity equality alone does not establish canonical identity.

For a known parsed denominator, require complete row disposition accounting before Puerto Rico filtering or model eligibility:

`INPUT = RETAINED_ASSERTION + EXACT_REPLAY + EXCLUDED + REVIEW_HELD`

If the input denominator is unknowable, the arithmetic state is `UNKNOWN`, not zero.

## 5. W07 — known-site field protocol

### Purpose

Collect repeatable observation opportunities that can later support a defensible known-site phenology target. This protocol is for visible fruiting evidence and search effort, not underground network reconstruction.

### Site eligibility

A site becomes `protocol_eligible` only when it has:

- a stable site identifier;
- a repeatable generalized search geometry or bounded site reference;
- documented access/permission state;
- a sensitivity classification;
- habitat and substrate scope sufficient to reproduce the intended search;
- no exact coordinate disclosure in the field interchange record.

Sensitive or unresolved sites remain withheld. Site selection should reflect repeatability and scientific coverage, not only past mushroom abundance.

### Visit scheduling

The study schedule must be frozen before the corresponding outcome is known. Prescheduled visits support the future forecast target. Opportunistic sightings are valuable occurrence evidence but do not silently become scheduled surveys.

A future shadow forecasting phase must continue verification visits independent of the model's predicted probability; otherwise selective follow-up can corrupt evaluation.

No universal sample-size threshold is imposed here. Use an initial feasibility period to estimate event frequency, detection difficulty, observer effects, missingness, and practical cadence; then freeze the analytical design before confirmatory evaluation.

### Survey dimensions

Every scheduled survey records:

- target taxon/guild/morphotype/macrofungal scope;
- scheduled, start, and end times;
- timezone;
- search geometry reference without exact coordinates;
- person-minutes;
- observer count and controlled pseudonyms;
- qualification classes;
- substrate, host, deadwood, and microsite coverage;
- constraints and equipment;
- visit status;
- target detection status;
- review state.

Observer arithmetic (`observer_count == number of observer pseudonyms`) and temporal monotonicity (`start <= end`) are semantic checks in addition to JSON Schema validation.

### Orthogonal visit and detection states

Do not overload one outcome field. The contract separates:

- visit status: `completed | incomplete | aborted | missed`;
- target detection: `detected | not_detected | not_assessed`.

Rules:

- `not_detected` is valid only for a completed visit with positive effort;
- a missed visit is `not_assessed`, never a zero/absence record;
- an aborted or incomplete visit may preserve an actual detection, but lack of detection cannot be upgraded to a negative survey;
- a detected target does not imply that every non-target taxon was searched and absent.

The required negative interpretation is exactly:

`documented non-detection under stated effort; not proof of absence`

### Fruiting observations

A fruiting-body observation is created only when visible fruiting evidence exists. `not_observed` is intentionally excluded from the fruiting-observation state enum; non-detection belongs to the survey record.

Allowed visible states are:

`primordia | emerging | expanding | mature | senescent | decomposing | unresolved`

These are evidence labels, not a deterministic biological state machine. Multiple states may coexist at one site.

### Episode and individual identity

Episode and individual fruiting-body identities use explicit states:

`unassigned | candidate | adjudicated`

Physical growth calculations are invalid unless repeated measurements can be defensibly bound to the same adjudicated fruiting body or another explicitly defined measurement unit. Two nearby mushrooms, two photographs, or two visits do not automatically represent one individual.

### Measurement evidence

Measurements may preserve cap diameter, height, stipe diameter, cluster span, occupied area, or another declared metric. Each measurement preserves unit, method, optional scale evidence, and optional uncertainty.

Capturing measurements does not authorize a growth model. It merely prevents the future growth question from depending on unscaled photographs or qualitative stage labels alone.

### Taxonomy and media

A field observation may reference a separate taxonomic assertion. Verification state must remain independent of location precision and platform quality grade.

Media IDs are evidence references. Media licensing and sensitive metadata handling are adjudicated separately. Do not expose embedded location metadata through otherwise generalized records.

### Environmental context

Field teams may preserve contemporaneous environmental measurements or notes when authorized, but W07 does not select predictors or bind them into a forecast. W11 later determines spatial support, units, timing, latency, missingness, uncertainty, and future-data-leakage rules.

### Safety and collection boundary

The protocol never requires destructive specimen collection. Any collection/vouchering action must follow site permissions, applicable law/rules, and qualified collection procedures outside this schema's implied authority. Unsafe conditions produce an aborted visit rather than pressure to complete the protocol.

## 6. Files in this package

- `governance/mycelial_planmax_w00_w02_w07_authority_20260909.json`
- `docs/mycelial/source_contracts/planmax_v1.json`
- `schemas/mycelial-field/v1/field-site.schema.json`
- `schemas/mycelial-field/v1/field-survey.schema.json`
- `schemas/mycelial-field/v1/fruiting-observation.schema.json`
- `tests/fixtures/mycelial_field_protocol/v1/cases.json`
- `tests/test_mycelial_field_protocol_design_v1.py`
- this execution document

The fixtures are synthetic and are prohibited from being represented as biological observations.

## 7. Exit gates

### W00 PASS candidate

- exact current-main base recorded;
- predecessor PR identity recorded without inheritance;
- allowed/prohibited capability boundary explicit.

### W01 PASS candidate

- source actions and coordinate handling represented explicitly;
- unresolved rights remain HOLD rather than default-allow.

### W02 PARTIAL candidate

- source hierarchy and failure taxonomy frozen;
- key source contracts recorded;
- live original biological payload acquisition remains unresolved, so W03 is not opened by implication.

### W07 DESIGN PASS candidate

Requires schema/fixture tests to execute successfully on the exact branch head. Even after a test PASS, no real field record is admitted by this package and no model is authorized.

## 8. Downstream state

- W03 original source bytes: `OPEN/BLOCKED_BY_ACCESS_OR_SOURCE_SPECIFIC_GATE`.
- W04 parsing/accounting: `NOT_READY` until W03 bytes exist.
- W05 identity/taxonomy/PR adjudication: `NOT_READY` for real records.
- W06 PR #238 certification: independent retry in progress; do not infer PASS from this package.
- W08 repeated field evidence: `NOT_STARTED`; protocol design is not evidence collection.
- W09 evidence-only application: `NOT_AUTHORIZED_BY_THIS_PACKAGE`.
- W10 eligible biological dataset: `NOT_READY`.
- W11 environmental feature dataset: `NOT_READY` for modeling.
- W12 calibration/model fitting: `NOT_AUTHORIZED`.
- W13 retrospective validation: `NOT_READY`.
- W14 prospective shadow validation: `NOT_READY`.
- W15 predictive release: `NOT_AUTHORIZED`.

The program remains evidence-first and fail-closed.
