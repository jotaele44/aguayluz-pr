# Road to 100 — normalized federation score

**Audit date:** 2026-08-17  
**Current main:** `1047c9b186017b0fdb715d81af843ddf17c45735`  
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

## Second-domain candidate: real-data partial export

Development branch `gpt/real-data-partial-export-v0-1` implements the bounded
`VALIDATE_AGUAYLUZ_REAL_DATA_PARTIAL_EXPORT` contract without changing this score
until the implementation is merged to `main`.

The candidate adds strict outage/recovery/continuity/source-registry/partial-manifest
schemas, a recurring source registry, a proxy-safe continuity taxonomy, and an
offline deterministic builder for a small `PRODUCTION_REAL_DATA_PARTIAL` package.
The package selects whole committed asset/event/project rows and may validly emit
zero recovery-project rows when no canonical recovery-project corpus exists.
Continuity rows derived from `EDGE-WP-*` or explicit fuel tokens remain
`candidate|provisional`, `identity_binding=proxy`, and `evidence_required=true`.

Machine-readable caveats preserve the current evidence boundary:

- EPA WATERS/NHDPlus hydro enrichment is `PROVISIONAL_PARTIAL`, bounded to VPU-21;
  off-network and no-waterbody outcomes remain explicit and are not extrapolated.
- MiLUMA outage acquisition is WAF/permission constrained and disabled by default;
  no missing live outage data is fabricated.
- PREPS requires an operator-frozen public-portal snapshot.
- EPA SDWIS is an authoritative regulatory water-quality source, not a complete
  operational water-outage denominator.
- Power↔water proximity never proves feeder/circuit identity.
- An explicit fuel token identifies only a fuel-sensitive candidate; current fuel
  stock, supplier, route, and outage cause remain unproven.

Exact offline verification commands for the candidate:

```bash
python -m pytest -q tests/test_real_data_partial_export.py tests/test_schemas.py
python scripts/build_real_data_partial_export.py \
  --generated-at 2026-08-17T01:15:00Z \
  --out /tmp/aguayluz-real-data-partial
python scripts/validate_repo.py
python scripts/federation_export.py --mode test
```

## Score adjudication after PR #120

PR #120 landed design authority for provider-agnostic regulatory observations, source receipts, conservative entity-link candidates, provider protocols and activation gates. It adds no live providers, persistence, scheduler, GUI/API surface or automatic entity promotion. No dimension changes: the landed design authority improves architectural definition, while the newly recognized implementation scope remains unfinished; data materialization and operator verification receive no credit.

## State reconciliation

- Core utility, water, alert, export, dashboard and desktop capabilities are on `main`.
- The real-data partial export candidate is development-lineage evidence only until separately merged; this roadmap does not infer main-lineage completion from branch CI.
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

1. Certify the bounded real-data partial-export candidate; if merged separately,
   re-freeze main before changing score or closing its issue manifestation.
2. Implement the PR #120 regulatory framework through separately reviewed provider, persistence, scheduler, API/GUI and promotion increments.
3. Reconcile #109's non-overlapping NHC/NEON work without duplicating the merged USGS authority.
4. Preserve the merged #118 direct-versus-context boundaries until eligible direct measurements exist.
5. Decompose mycelial Phase 1 by approved ballots.
6. Acquire authorized outage provenance.

## Machine-readable authority

See `docs/unfinished_implementation_ledger.v1.json`. Only evidence on `main` closes an item.
