# NEON MAX integration audit — 2026-09-03

## Scope

This audit evaluates the NSF National Ecological Observatory Network (NEON) integration in `aguayluz-pr` on the live repository state. It distinguishes implemented code, executed evidence, unresolved live-provider evidence, and deliberately deferred scientific products.

## Certification state

**Overall: PROVISIONAL / BLOCKED on live token-gated product-download certification.**

The keyless NEON integration is implemented and has live evidence. The token-gated data-download path is implemented, fixture-tested, checksum/QA guarded, and instrumented with a secret-safe ingest receipt, but the available live-smoke evidence classifies the configured credential as `AUTH_REJECTED` / `CREDENTIAL_REJECTED`. Therefore no claim is made that a real NEON CSV manifest/download has passed end-to-end on the current credential.

## Implemented chain

```text
NEON API v0
  -> canonical NeonClient / X-API-Token semantics
  -> D04 Puerto Rico site denominator: CUPE, GUAN, GUIL, LAJA
  -> keyless site/product availability ingestion
  -> version-aware availability snapshot and publication-event delta
  -> months_sha256 backfill detection
  -> token-gated product manifest/download path
  -> published MD5 verification
  -> QA-flag rejection
  -> unit-bound CSV-column mapping
  -> daily aggregation
  -> monitoring_reading rows
  -> alert promotion with explicit product routing
  -> federation export glob
  -> canonical backend readings registry
  -> monitoring quality registry
  -> bounded live-smoke control
```

## Evidence matrix

| Gate | State | Basis |
|---|---|---|
| NEON provider identity | PASS | NSF NEON canonical package/docs |
| PR site denominator | PASS | exactly CUPE, GUAN, GUIL, LAJA |
| Anonymous metadata access | PASS | live keyless ingest evidence |
| Availability state persistence | PASS | committed previous-state registry |
| Publication delta semantics | PASS | new month/backfill/new product/new release/gap model |
| Backfill detection | PASS | sorted-month SHA-256 invariant |
| Token handling | PASS | X-API-Token; no bearer fallback; rejected token fails closed |
| Product download implementation | PASS (code) | manifest/download/parser path exists |
| Real token-gated product download | BLOCKED | current live smoke classified AUTH_REJECTED |
| Download integrity | PASS (tested) | published MD5 required before parsing |
| QA rejection | PASS (tested) | NEON QA-flagged rows dropped |
| Unit binding | PASS (tested) | units bind to value column, not product fallback |
| Synthetic fixture disclosure | PASS | synthetic fixtures explicitly marked |
| Ingest receipt | PASS | header/matched-column/unit/count, secret-free |
| Backend `kind=neon` observability | PASS on this branch | single canonical reading registry restored |
| Monitoring quality registration | PASS on this branch | streamflow + gage_height registered as reference series |
| Self-service live smoke | PASS (control installed on this branch) | read-only, secret-safe, no persistence/notification/promotion |
| `water_quality` backend vector | OPEN | heterogeneous physical units under one metric require registry/schema redesign |
| precipitation readings | DEFERRED | metric enum/parser promotion not yet implemented |
| soil-moisture readings | DEFERRED | metric enum/parser promotion not yet implemented |
| soil-temperature readings | DEFERRED | metric enum/parser promotion not yet implemented |
| evapotranspiration readings | DEFERRED | metric enum/parser promotion not yet implemented |
| retired site/product tombstones | OPEN | current registry drops retired pairs rather than preserving tombstones |
| full provider-neutral environmental source registry | OPEN | no merged first-class registry unifying NEON/USGS/NOAA/NASA/LTER/WQP/DRNA was found on main |

## Invariants

1. Source presence is not treated as observation certification.
2. A rejected credential is never silently downgraded to anonymous access for a gated endpoint.
3. Bootstrap state produces no historical flood of synthetic publication events.
4. A changed historical month is detectable even when `latest_month` is unchanged.
5. A downloaded file must pass provider-published MD5 before parsing.
6. A CSV file with no documented value column is skipped rather than guessed.
7. QA-flagged observations are excluded before aggregation.
8. Unit identity follows the selected column.
9. Ecological products outside AguaYLuz water/power scope remain tracked but do not generate subject-misclassified alerts.
10. NEON publication events never become life-safety critical alerts.
11. Live-smoke receipts cannot contain token values, response bodies, headers, or exception text.
12. No token-gated NEON reading is certified from synthetic fixtures alone.

## Remaining MAX vector

### P0 — live evidence closure

Replace/repair the NEON credential in the runtime secret store and execute the bounded live smoke. Require HTTP 200 and exact D04 denominator equality. Then execute one token-gated product download and inspect `data/neon_ingest_receipt.json` against the documented product-column map. Preserve response/manifest provenance and hashes without persisting secrets.

### P1 — heterogeneous water-quality model

Do not add `water_quality` to the canonical backend vector while one series metadata entry can encode only one unit. Redesign series identity so parameter/product code and unit are first-class, then add positive and negative tests proving nitrate, conductance, and dissolved-gas rows cannot be mislabeled or coalesced.

### P2 — deferred hydroclimate products

Promote precipitation, soil moisture, soil temperature, and evapotranspiration only in schema+parser+tests in the same change. Each product must have an independently verified real CSV header before production promotion.

### P3 — provider-neutral source plane

Create one environmental-provider contract covering at minimum NEON, USGS, NOAA/NWS, NASA Earthdata, Luquillo LTER/USFS, EPA/WQP, and DRNA. Separate configuration/reachability/metadata discovery from observation ingestion and from certified-series promotion. Provider registration alone must never imply observational coverage.

### P4 — retirement/version semantics

Replace silent disappearance of retired site/product pairs with tombstoned state carrying first-seen, last-seen, retirement-detected-at, previous month hash, and source manifestation provenance.

## Final claim boundary

The current branch closes a real application-wiring defect and restores the bounded live-smoke control. It does **not** claim `AGUAYLUZ NEON INTEGRATION CERTIFIED` because the live token-gated product path remains blocked by credential rejection and several explicitly deferred data-model vectors remain open.

Certification may advance to **CERTIFIED** only after the defined scope has zero unresolved residue: valid live credential, exact four-site denominator, at least one real product download with verified headers/hash/QA/unit semantics, canonical backend observability, provider-neutral provenance, and all included product metrics fully classified.
