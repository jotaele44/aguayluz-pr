# Mycelial Phase 1 Ballot A design package v1.0.0

## Authority and exact base

- Governance: `docs/adr/ADR-0002-mycelial-phase-0-baseline-and-phase-1-admission.md`
- Human design-only ballot receipt: `5175521569`
- Research-ingest prerequisite HOLD review: `4851413154`
- Exact branch base: `a6b1bc591ef23d0558865d437ab2806319119bbb`
- Classification: `design_only`
- Staging expiry preserved: `2026-12-31`

This package specifies declarative contracts only. It does not admit data or provide
executable ingestion, persistence, runtime, API, GUI, scheduler, notification, export,
federation, analytics, ranking, connectivity, coordinate disclosure, or infrastructure inference.

## Versioned canonical schemas

All schemas use JSON Schema Draft 2020-12 and package version `1.0.0`.

| Schema | Scope |
|---|---|
| `source-license-provenance.schema.json` | Source authority, stable identity, acquisition design, licensing, retention, attribution, hashes, evidence tier, replay identity, duplicate-candidate identity, and non-exact location representation |
| `sampling-effort.schema.json` | Protocol/version, temporal bounds, generalized search geometry, person effort, observer qualifications, target scope, substrate/microsite coverage, constraints, equipment, and outcome semantics |
| `taxonomic-evidence.schema.json` | Rank, verification class, determiner, determination date, authority/version, synonym resolution, voucher/media evidence, and confidence basis |
| `temporal-environmental-evidence.schema.json` | Timezone normalization, aggregation, lag/lead, latency, missing-period behavior, future-data leakage prevention, and predictor evidence sheets |
| `lifecycle-evidence.schema.json` | Stable sites, visible-fruiting observations, media, environmental snapshots, and evidence-bound transition assertions |
| `receipt-accounting.schema.json` | Complete/partial/failed/rejected/rolled-back receipts, row rejection reasons, correction, retraction, duplicate, replay, supersession, and rollback designs |

## Scientific and evidentiary semantics

1. A negative survey is documented non-detection under recorded effort; it is not proof of absence.
2. Missing coordinates, dates, taxa, effort, or environmental values remain missing.
3. Exact replay and duplicate candidacy are distinct relationships.
4. Contradictory assertions remain separate until adjudicated.
5. Corrections and supersessions add relationships; they do not destroy history.
6. Retractions preserve the predecessor and the retraction event.
7. Receipt accounting is deterministic:
   `attempted = accepted + rejected + review_queue + exact_replays`.
8. Environmental values require explicit timezone, aggregation, lag/lead, publication latency,
   missing-period, and future-data-leakage controls.
9. Lifecycle transitions require an episode ID, evidence endpoints, scientific-basis reference,
   contradiction state, and review state. No deterministic biological state graph is admitted.
10. Site contracts prohibit exact coordinate values and request-controlled disclosure switches.
    Until Ballot D is approved, only `none`, `generalized`, or `withheld` representations are allowed.

## Fixture coverage

`tests/fixtures/mycelial_phase1_design/v1/cases.json` contains synthetic design fixtures
covering positive, negative, missing, stale, contradictory, partial, failed, rejected,
correction, retraction, duplicate, exact replay, supersession, and rollback cases.
It is not an admitted biological dataset.

## Boundary proof

The package changes only:

- this document;
- nested JSON Schemas;
- synthetic JSON fixtures;
- one static schema and semantic conformance test.

It adds nothing under `research/`, `src/`, `server/`, `scripts/`, `dashboard/`, `data/`,
`.github/workflows/`, `schemas/sql/`, or federation configuration. It changes no feature flag.

## Required next gates

The draft PR must reach terminal final-head workflow success and be rechecked against then-current
`main`. Ready transition and expected-head merge require separate authorization. Only after the
design package is merged may a new human ballot consider `APPROVE_RESEARCH_INGEST`.
