# Permanent Lago Patillas stage-volume recovery v0.4.1

Status: design-only, source-materialized, runtime-disabled.

## Recovery result

The authoritative USGS ScienceBase archive `Patillas_Terrain_2019.gdb.zip`
was recovered from workflow artifact `8912513566`.

- Archive bytes: `27,171,688`
- Published and observed MD5: `562ed7f0458a5c84b379963a90b9c8d1`
- SHA-256: `3beac301b1521a197837ebb49eff701e2774385cb34f220e3546c82c5d732ea7`
- Retrieval: `2026-08-04T23:24:26Z`
- Table: `Patillas2019_volume`
- Rows: `24`
- Fields: `Pool_Elevation_m`, `Storage_capacity_mcm`
- Datum: `PRVD02`

The table was read through the OpenFileGDB driver. No OCR, manual
transcription, inserted row, or corrected value was used.

## Exact source preservation

The package preserves:

- the exact three FileGDB components for `Patillas2019_volume`;
- a source-order CSV retaining FIDs 1 through 24;
- the exact FGDC metadata XML;
- sanitized response headers and hashes of the original raw headers;
- archive size, MD5, SHA-256, source URL, retrieval time, and artifact digest;
- a stage-ascending parsed table and a cross-bound model and receipt.

The full 27 MB archive is not duplicated in Git. Its byte identity remains
bound by the archive hash and the retained workflow artifact receipt. The
table-specific FileGDB source bytes are committed directly.

## Published-precision plateau

The source publishes:

| Stage, m PRVD02 | Storage, million m³ |
|---:|---:|
| 44.55 | 0.00 |
| 45.55 | 0.00 |

These are retained exactly. The model makes no strict storage-increase claim.
Exact lookup at either endpoint is allowed, but interpolation inside
`(44.55, 45.55)` is prohibited. No positive slope, hidden volume, or corrected
value is inferred.

Outside that declared segment, interpolation is piecewise linear between
adjacent published points. Extrapolation is prohibited everywhere.

## Metadata checksum contradiction

The downloaded FGDC XML has the expected size of 29,951 bytes but its observed
MD5 differs from the ScienceBase catalog value. The contradiction is preserved
as nonblocking for the stage-volume table because the authoritative FileGDB
archive itself matches its published size and MD5 exactly.

## Real-window decision

Materializing the stage-volume relation removes one evidence blocker. A real
Patillas-Guayama balance remains blocked because synchronized T1 treatment
withdrawal, downstream terminal flow, full-window release, precipitation
volume, evaporation, documented operational losses, and complete calibration
and revision evidence are not admitted.

No real balance is executed. No residual is interpreted as leakage, theft,
fraud, illegal diversion, unauthorized activity, or an exact failure location.

## Activation boundary

This package adds no network client, persistence, API, GUI, export, alert,
notification, scheduler, migration, deprecation, production polling, or
control action. Any such promotion requires a separate approved ballot.
