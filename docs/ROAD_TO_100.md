# Road to 100 — normalized federation score

**Audit date:** 2026-08-04  
**Current main:** `cda1aa1b42f5bd13ab61db9d78a302cd6e953c23`
**Scoring model:** code completeness 20%; main-branch availability 15%; CI enforcement 15%; data materialization 15%; operator verification 15%; GUI completeness 10%; federation readiness 10%.

## Current normalized score: 81.55 / 100

| Dimension | Weight | Score | Weighted |
|---|---:|---:|---:|
| Code completeness | 20 | 94 | 18.80 |
| Main-branch availability | 15 | 75 | 11.25 |
| CI enforcement | 15 | 88 | 13.20 |
| Data materialization | 15 | 78 | 11.70 |
| Operator verification | 15 | 68 | 10.20 |
| GUI completeness | 10 | 82 | 8.20 |
| Federation readiness | 10 | 82 | 8.20 |

## Score adjudication after PR #120

PR #120 landed design authority for provider-agnostic regulatory observations, source receipts, conservative entity-link candidates, provider protocols and activation gates. It adds no live providers, persistence, scheduler, GUI/API surface or automatic entity promotion. No dimension changes: the landed design authority improves architectural definition, while the newly recognized implementation scope remains unfinished; data materialization and operator verification receive no credit.

## PR #168 candidate: bounded real-data partial export

Draft PR #168, refreshed against exact base
`c7860f0c900756bed60bccaee6021ee18aabe3dc`, adds an offline deterministic
`PRODUCTION_REAL_DATA_PARTIAL` package. It selects whole committed rows, permits
an explicitly empty recovery-project stream, and emits only evidence-gated
continuity candidates. It does not change the score while unmerged.

The candidate preserves these boundaries: power-water proximity is discovery,
not feeder identity; a fuel token does not prove stock, supplier, route, or
outage cause; VPU-21 hydro evidence is not Puerto Rico-wide coverage; and
permission-constrained live outage inputs are not fabricated.

## State reconciliation

- Core utility, water, alert, export, dashboard and desktop capabilities are on `main`.
- PR #120 is merged design authority only. Live provider adapters, durable persistence, scheduling, GUI/API exposure and adjudicated entity promotion remain implementation gaps.
- PR #116 is the current-main authority for auditable USGS water-category coverage. Live verification remains an operator task.
- Cave/karst core and read-only surface are current-main capabilities.
- PR #118 is current-main context-only control-plane evidence and preserves direct current observations `0`, `current_condition.status = unknown`, no automatic leakage finding and no root-cause claim.
- Mycelial Phase 1 remains independently balloted and unimplemented.
- Authorized live outage provenance remains externally constrained.

### PR #109 live-data evidence to adjudicate

The PR #109 vector adds keyless USGS OGC field-measurements, USGS annual peaks,
and NHC active-cyclone ingestion. Its current materialization evidence records
6,915 field-measurement readings across 89 wells, 8,317 annual peaks across 244
sites for water years 1899-2025, and a zero-row NHC active-cyclone pull because
the active storm was outside the Atlantic/PR threat envelope. These close the
Laguna Cartagena "not retrievable through the new API" assumption at the adapter
level, but the roadmap score should change only after the branch lands on
`main` and the PR #109/#116 overlap is adjudicated.

## Priority exit sequence

1. Certify PR #168 on current main without promoting partial data to complete coverage.
2. Implement the PR #120 regulatory framework through separately reviewed provider, persistence, scheduler, API/GUI and promotion increments.
3. Reconcile #109's non-overlapping NHC/NEON work without duplicating the merged USGS authority.
4. Preserve the merged #118 direct-versus-context boundaries until eligible direct measurements exist.
5. Decompose mycelial Phase 1 by approved ballots.
6. Acquire authorized outage provenance.

## Machine-readable authority

See `docs/unfinished_implementation_ledger.v1.json`. Only evidence on `main` closes an item.
