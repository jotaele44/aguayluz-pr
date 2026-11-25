# Ionosphere RC0 — staged audit and contract prototype

Scope: TEC and ROTI context for Aguayluz. State: AUDIT_ONLY; live integration,
release, production monitoring and reusable skill promotion are BLOCKED.
Repository stable ID: 1257600730. Baseline: add9e356618451bec3b1f156a26f6f7bda705077.
Audit date: 2026-10-23. Preview expiry: 2026-11-23.

## Evidence and limitations

NOAA documentation: https://www.spaceweather.gov/products/glotec
NOAA describes a data-assimilative global model, default grid 2.5 degrees latitude
by 5 degrees longitude, TEC in TECU, and observational coverage/quality flags.
Where observations are absent, values relax toward background climatology.
Documentation retrieval is not a frozen measurement snapshot or verified local coverage.
The candidate data directory https://services.swpc.noaa.gov/products/glotec/geojson_2d_urt/
returned HTTP 403 in this execution environment. Search also returned a 403 when
opening it. The alternate services.swpc.woc.noaa.gov directory also returned 403 through search. This establishes an acquisition failure here, not universal unavailability.
No measurement bytes, schema signature, counts or local cell identities were acquired.
No source hashes are invented. The API reports a historical audit, not a live probe.

ROTI is standard deviation of TEC rate of change over a specified interval.
Definition: https://swe.ssa.esa.int/documents/d/guest/product_catalogue_summary
IGS product discovery https://igs.org/products includes a high-latitude ROTI
product whose advertised domain does not establish Puerto Rico coverage.
A suitable regional provider and its methods remain UNRESOLVED.

## Implemented boundary

A pure shared-record validator preserves whole rows and separates unknown quality,
missing values, zero, stale timestamps, spatial binding and impact. It is a PROPOSED
producer contract tested with explicit synthetic fixtures, not a raw NOAA adapter,
validated GNSS algorithm, or persisted consumer integration. It performs no downloads.
The audit API and discoverable bilingual panel are reachable only with both preview
flags enabled. No alerts, database writes, production scheduler or external credentials.
Retry reloads audit status; it does not retry NOAA acquisition.

## Fixed backlog and gates

| ID | Gate | State | Acceptance |
|---|---|---|---|
| ION-01 | Repository identity and source documentation audit | PASS | Stable repository ID; source limitations documented |
| ION-02 | Shared contract + disabled preview | PROVISIONAL | Contract, API, UI and default-disabled tests pass |
| ION-03 | Frozen real TEC acquisition | BLOCKED | Raw bytes, URL, retrieval UTC, SHA256, schema, count, units and null codes |
| ION-04 | Puerto Rico spatial coverage | OPEN | Inspect actual coordinates/cells and quality; preserve CRS; no bbox-as-identity |
| ION-05 | ROTI provider and method | UNRESOLVED | PR coverage, station IDs, cadence, interval, units, bias/cycle-slip handling |
| ION-06 | PITIRRE producer binding | OPEN | Verify repository stable ID, current code, ownership and exact serialized export |
| ION-07 | Persisted consumer integration | OPEN | Idempotent producer-to-consumer replay, count conservation, failure receipts |
| ION-08 | Independent full verification | OPEN | Real capture tests, enabled/disabled GUI paths, build, regression, source failure negatives |
| ION-09 | Rollback and exact release | BLOCKED | Restore data/code; exact commit CI and artifact checks; all applicable gates PASS |
| ION-10 | Deploy, monitor, promote skill | BLOCKED | Verified deployed release, freshness monitoring, then bounded reusable skill |

No denominator reduction: passing prototype tests cannot close ION-03 through ION-10.
No electricity outage or geomagnetically induced current claim follows from TEC/ROTI.
Global model cells must not be relabeled as municipal observations. Do not calculate
ROTI from low cadence global model TEC and call it receiver-level ROTI.

## Verification and recovery

See TERMINAL_READY_IONOSPHERE.txt for single-line commands and test results.
Default flags unset: no sidebar entry or frontend route; API returns 404.
Rollback: unset both flags and rebuild dashboard; no data mutation to restore in RC0.
Future persistence must have a separate data restore rehearsal before release.
Execution plan score: 95/100 (design judgment); hardening design: 95/100.
Execution readiness is not a numeric certification and remains BLOCKED.

## Executed validation (RC0)

- Python contract/API and parity regression: 12 PASS; 25 parameter subtests PASS.
- New panel unit tests: 2 PASS. Existing CaveKarstPage unit gate: 4 PASS.
- GUI capability inventory: PASS, no baseline regeneration.
- Changed JSX lint: PASS. Default Vite build: PASS; dist/index.html exists.
- Required full browser gate: 1 PASS / 30 runner failures before browser launch.
- Enabled preview browser gate: 1 runner failure before browser launch.
- Browser installation attempted: download returned truncated/non-ZIP content.
- Browser behavioral verification: BLOCKED, not an application regression finding.
- Independent verifier, production deployment, real producer ingestion and rollback: not certified.

Bounded acquisition attempts are exhausted for the two NOAA service hosts tested here;
provider discovery as a whole is not exhausted. Skill promotion is withheld.
