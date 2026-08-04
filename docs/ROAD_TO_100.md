# Road to 100 — normalized federation score

**Audit date:** 2026-08-04
**Reconciled main:** `b14e96dd9b274200599daa313c46884aa4ad301c`
**Scoring model:** code completeness 20%; main-branch availability 15%; CI enforcement 15%; data materialization 15%; operator verification 15%; GUI completeness 10%; federation readiness 10%.

## Current normalized score: 81.55 / 100

| Dimension | Weight | Prior score | Reconciled score | Weighted |
|---|---:|---:|---:|---:|
| Code completeness | 20 | 94 | 94 | 18.80 |
| Main-branch availability | 15 | 75 | 75 | 11.25 |
| CI enforcement | 15 | 88 | 88 | 13.20 |
| Data materialization | 15 | 78 | 78 | 11.70 |
| Operator verification | 15 | 65 | 68 | 10.20 |
| GUI completeness | 10 | 82 | 82 | 8.20 |
| Federation readiness | 10 | 82 | 82 | 8.20 |

The prior normalized score was 81.10. PR #118 changes only the operator-verification dimension: its exact-head live probe produced a reproducible, secret-safe acquisition receipt and replay evidence. It does not increase code-completeness or main-branch-availability credit because the implementation remains an open draft PR. It does not increase data-materialization credit because the result is `context_only`, direct current observations are `0`, and `current_condition.status` remains `unknown`.

PR #120 landed design authority for provider-agnostic regulatory observations, source receipts, conservative entity-link candidates, provider protocols and activation gates. It adds no live providers, persistence, scheduler, GUI/API surface or automatic entity promotion, so it does not change the normalized score; it records implementation scope that remains unfinished.

## State reconciliation

- Core utility, water, alert, export, dashboard and desktop capabilities are on `main`.
- Mycelial Phase 0 and its governance ADR are on `main`; combined Phase 1 PR #111 was closed unmerged and is not implementation authority.
- PR #109 contains USGS/NEON/NHC work but overlaps newer USGS coverage.
- PR #116 is the ten-category USGS coverage candidate and requires live receipts plus current-main reconciliation.
- PR #114 is the cave/karst core candidate; PR #115 is its stacked read-only API/GUI candidate.
- PR #118 is a separate Laguna Cartagena current-condition control-plane candidate with an exact-head live probe.
- PR #118 preserved `context_only`, direct current observations `0`, `current_condition.status = unknown`, no automatic leakage finding and no root-cause claim.
- PR #120 is merged design authority only. Live provider adapters, durable persistence, scheduling, GUI/API exposure and adjudicated entity promotion remain implementation gaps.
- Live LUMA outage provenance remains externally constrained.

## Priority exit sequence

1. Reconcile #109 and #116 by concept and preserve one authoritative implementation per USGS category.
2. Reconcile #114 and #115 onto current `main`, preserving pilot-only and coordinate-disclosure boundaries.
3. Keep #118 separate from #109/#116; retain its direct-versus-context distinction and fail-closed current-condition result.
4. Implement the PR #120 regulatory framework through separately reviewed provider, persistence, scheduler, API/GUI and promotion increments.
5. Decompose future mycelial Phase 1 work by adopted independent ballots.
6. Run bounded network-enabled USGS and NEON receipts before promoting `implemented_unverified_live` categories.
7. Obtain an authorized outage source before T1 outage lifecycle claims.

## Machine-readable authority

See `docs/unfinished_implementation_ledger.v1.json`. Only evidence on `main` closes an item. Open PR, operator-run, external-data, rescue and governance-only states remain separately classified.
