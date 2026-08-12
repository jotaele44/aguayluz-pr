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

## State reconciliation

- Core utility, water, alert, export, dashboard and desktop capabilities are on `main`.
- PR #120 is merged design authority only. Live provider adapters, durable persistence, scheduling, GUI/API exposure and adjudicated entity promotion remain implementation gaps.
- PR #116 is the current-main authority for auditable USGS water-category coverage. Live verification remains an operator task.
- Cave/karst core and read-only surface are current-main capabilities.
- PR #118 is current-main context-only control-plane evidence and preserves direct current observations `0`, `current_condition.status = unknown`, no automatic leakage finding and no root-cause claim.
- Mycelial Phase 1 remains independently balloted and unimplemented.
- Authorized live outage provenance remains externally constrained.

## Priority exit sequence

1. Implement the PR #120 regulatory framework through separately reviewed provider, persistence, scheduler, API/GUI and promotion increments.
2. Reconcile #109's non-overlapping NHC/NEON work without duplicating the merged USGS authority.
3. Preserve the merged #118 direct-versus-context boundaries until eligible direct measurements exist.
4. Decompose mycelial Phase 1 by approved ballots.
5. Acquire authorized outage provenance.

## Machine-readable authority

See `docs/unfinished_implementation_ledger.v1.json`. Only evidence on `main` closes an item.