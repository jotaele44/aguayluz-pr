# Road to 100 — normalized federation score

**Audit date:** 2026-08-04  
**Scoring model:** code completeness 20%; main-branch availability 15%; CI enforcement 15%; data materialization 15%; operator verification 15%; GUI completeness 10%; federation readiness 10%.

## Current normalized score: 81.10 / 100

| Dimension | Weight | Score | Weighted |
|---|---:|---:|---:|
| Code completeness | 20 | 94 | 18.80 |
| Main-branch availability | 15 | 75 | 11.25 |
| CI enforcement | 15 | 88 | 13.20 |
| Data materialization | 15 | 78 | 11.70 |
| Operator verification | 15 | 65 | 9.75 |
| GUI completeness | 10 | 82 | 8.20 |
| Federation readiness | 10 | 82 | 8.20 |

The former ~90% figure described the utility/water producer before recent mycelial, cave/karst and expanded USGS work. It is stale as a program-wide measure.

## State reconciliation

- Core utility, water, alert, export, dashboard and desktop capabilities are on `main`.
- Mycelial Phase 0 and its governance ADR are on `main`; the combined Phase 1 PR #111 was closed unmerged and is not implementation authority.
- PR #109 contains USGS/NEON/NHC work but overlaps newer USGS coverage.
- PR #116 is the current ten-category USGS coverage candidate and requires live receipts plus full CI.
- PR #114 is the cave/karst core candidate; PR #115 is its stacked read-only API/GUI candidate.
- Live LUMA outage provenance remains externally constrained.

## Priority exit sequence

1. Reconcile #109 and #116 by concept and preserve only one authoritative implementation per USGS category.
2. Reconcile #114 and #115 onto current `main`, preserving the pilot-only and coordinate-disclosure boundaries.
3. Decompose any future mycelial Phase 1 work by the adopted independent ballots.
4. Run bounded network-enabled USGS and NEON receipts before promoting `implemented_unverified_live` categories.
5. Obtain an authorized outage source before T1 outage lifecycle claims.

## Machine-readable authority

See `docs/unfinished_implementation_ledger.v1.json`. Candidate PRs receive partial main-availability credit but do not close tasks until merged and verified.
