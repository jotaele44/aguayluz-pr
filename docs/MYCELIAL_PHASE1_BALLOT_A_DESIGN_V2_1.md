# Mycelial Phase 1 Ballot A design package v2.1.0

## Authority and exact base

- Governance: `docs/adr/ADR-0002-mycelial-phase-0-baseline-and-phase-1-admission.md`
- Human design-only ballot receipt: `5175521569`
- Research-ingest prerequisite HOLD review: `4851413154`
- Exact live `origin/main` base: `70db651834a7f2cf3d11dfa35b6e29db851b7e46`
- Classification: `design_only`
- `APPROVE_RESEARCH_INGEST`: `HOLD`
- Feature flag default: `disabled`
- Staging expiry: `2026-12-31`

This package is declarative only. It does not admit research ingestion,
data persistence, runtime behavior, API routes, GUI surfaces, schedulers,
notifications, exports, federation wiring, calibrated analytics, location
ranking, connectivity outputs, public exact sensitive coordinates, or
infrastructure inference.

## Versioned canonical contracts

All contracts are JSON Schema Draft 2020-12 under
`schemas/mycelial-phase1/v2.1/` and require `schema_version = 2.1.0`.

| Contract | Scope |
|---|---|
| `source-license-provenance.schema.json` | Source authority, stable source-record identity, acquisition design, license terms, retention, attribution, content hashes, replay identity, duplicate-candidate identity, and non-exact coordinate representation |
| `sampling-effort.schema.json` | Survey protocol, bounded temporal effort, generalized search geometry, observer effort, qualifications, target scope, substrate/host/deadwood/microsite coverage, constraints, equipment, and non-detection semantics |
| `taxonomic-evidence.schema.json` | Assertion rank, determiner, determination date, authority/version, synonym status, voucher/media support, verification class, and confidence basis |
| `temporal-environmental-evidence.schema.json` | Timezone normalization, aggregation window, lag/lead windows, source latency, missing-period behavior, future-data leakage guard, and environmental evidence sheets |
| `lifecycle-evidence.schema.json` | Stable generalized sites, visible-fruiting observations, environmental snapshots, transition assertions, contradiction state, supersession hooks, and review state |
| `receipt-accounting.schema.json` | Complete, partial, failed, rejected, and rolled-back receipt design; row rejection reasons; correction, retraction, duplicate, replay, supersession, and rollback relationships |

## Scientific semantics

1. Positive observations remain evidence assertions, not calibrated predictions.
2. Negative surveys represent documented non-detection under recorded effort; they are not proof of absence.
3. Missing coordinates, dates, taxa, effort, or environmental values remain missing.
4. Stale environmental values are flagged and preserved; they are not silently refreshed.
5. Contradictory assertions remain separate until a future adjudication process is approved.
6. Exact replay identity and duplicate-candidate identity remain distinct.
7. Corrections, retractions, supersessions, and rollbacks preserve historical assertions through immutable relationship designs.
8. Receipt accounting is deterministic: `attempted = accepted + rejected + review_queue + exact_replays`.
9. Temporal matching forbids future-data leakage and requires explicit source observation and acquisition timing.
10. Environmental evidence sheets describe product suitability and gaps only; they do not create predictors, rankings, or model outputs.

## Synthetic fixture package

`tests/fixtures/mycelial_phase1_design/v2.1/cases.json` is synthetic and
fixture-only. It covers:

- positive
- negative
- missing
- stale
- contradictory
- partial
- failed
- rejected
- correction
- retraction
- duplicate
- replay
- supersession
- rollback

Synthetic fixture provenance is prohibited from production admission. The package
does not grant permission to run ingestion or convert fixture records into
persisted research data.

## Boundary proof

The v2.1 package changes only:

- this design document;
- JSON Schemas under `schemas/mycelial-phase1/v2.1/`;
- synthetic fixtures under `tests/fixtures/mycelial_phase1_design/v2.1/`;
- the static certification test `tests/test_mycelial_phase1_design_v2_1.py`;
- the final-head certification report under `reports/mycelial_phase1_design/`.

It adds nothing under `research/`, `src/`, `server/`, `scripts/`, `dashboard/`,
`data/`, `.github/workflows/`, `schemas/sql/`, `.federation/`, runtime
configuration, or federation configuration.

## PR disposition

This package is eligible only for a draft PR. It must not be marked ready,
merged, or auto-merged by this vector. Any future transition from design-only to
research ingestion requires a separate authorization after receipt `4851413154`
is lifted from HOLD.
