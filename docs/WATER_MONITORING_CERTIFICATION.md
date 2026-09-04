# AguaYLuz Water Monitoring Certification

## Current state

`PROVISIONAL` — the map-first monitoring implementation and fail-closed contracts are materially advanced, but the complete defined certification scope is not closed.

`AGUAYLUZ WATER MONITORING CERTIFIED` is **not issued** by this checkpoint.

## Passed implementation boundary

- Existing metric-safe monitoring charts remain canonical for time-series rendering.
- `/monitoring` uses the canonical `AssetMap` rather than a second monitoring-map implementation.
- Rivers, reservoirs, rainfall, groundwater, and coastal layers bind only to verified materialized asset subtypes: `stream_gage`, `reservoir`, `precipitation_gauge`, `groundwater_well`, and `tide_gauge`.
- Series readiness and geometry readiness are independent gates.
- Missing geometry is never replaced by a name-derived, nearest-neighbor, centroid, or category-based fallback.
- Mutable ArcGIS source acquisition has restartable snapshot tooling with retrieval UTC, raw-page SHA256, resolved URLs, page offsets/counts, CRS declaration, stable-ID checks, and a canonical combined serialization hash.
- Watershed topology tooling preserves one output row per station, complete candidate watershed sets, and explicit spatial states.
- Federation capability binding inherits HAF `certification_required`, evidence-priority fail-closed identity policy, and unresolved fail-closed policy.

## Authoritative source adjudication

### Watersheds — `OPEN`

Authoritative source identified: Puerto Rico Planning Board SIGE / MiPR `MIPR/Geologia_v10_N`, layer 0, `Cuencas Hidrográficas`.

The layer is polygon geometry in source CRS EPSG:32161, supports GeoJSON and pagination, and exposes `GlobalID`, `CUENCA_ID`, and `NOMBRE`. Certification still requires an executed frozen snapshot plus geometry/topology validation against the exact frozen manifestation.

### Physical well candidates — `CANDIDATE_NOT_IDENTITY`

SIGE exposes `Pozos Agua Potable JCA` and `Pozo AAA` point layers. These may contribute physical/source candidate geometry. They are not DRNA water permits, water franchises, or enforcement findings and therefore cannot establish authorization or illegality.

### DRNA authorization/extraction plane — `BLOCKED`

Within the bounded current discovery, no exhaustive authoritative machine-readable DRNA permit/franchise rowset has been identified. General permitting GIS, JCA well points, AAA well points, source absence, proximity, same-parcel coincidence, or name similarity do not substitute for DRNA authorization identity.

### Water quality — `PARTIAL`

The repository already has USGS discrete-sample and token-gated NEON adapters that emit `metric=water_quality`. `parameter_code` preserves what was measured and units are not invented. The generic monitoring frontend still requires an analyte/parameter-code + unit specific selector contract before water-quality measurements can be safely exposed as one chart family.

## A — Public monitoring experience

Required: rivers, reservoirs, rainfall, groundwater, coastal water, map geometry, freshness, source provenance, metric/unit identity, datum handling, stale-source behavior, historical context, and incident linkage.

Current live station families are `PASS` for the bounded series+asset-geometry contract. Watersheds, extraction, and water quality remain outside the complete certification claim as stated above.

## B — Extraction regulatory semantics

Canonical physical and regulatory nodes:

- `physical_well`
- `intake`
- `permit`
- `water_franchise`
- `operator`
- `owner`
- `parcel`
- `enforcement_action`
- `withdrawal_observation`

Permitted cardinalities are `1:1`, `1:N`, `N:1`, `N:N`, `0:1`, and `UNRESOLVED`.

Identity priority is stable ID → authoritative binding → certified geometry + independent alias/ID → point-in-polygon + corroboration → authoritative alias + spatial/temporal support → historical continuity + corroboration → proximity → unresolved.

`CONFIRMED_UNAUTHORIZED` requires an authoritative enforcement/adjudicative finding with a stable finding identifier. `AUTHORIZED` requires an authoritative physical-well↔permit binding and permit identifier. Source absence, proximity, name similarity, parcel coincidence, or count equality cannot establish illegality or identity.

## C — Hydrologic digital twin

Canonical topology:

`watershed → subwatershed → river_segment → gauge → reservoir → intake → treatment_asset → distribution_context`

and

`aquifer → recharge_zone → well/spring → withdrawal → watershed/coastal receiving context`.

Edges must preserve provenance and may be `AUTHORITATIVE`, `CERTIFIED_GEOMETRIC`, `DERIVED_TOPOLOGICAL`, `CANDIDATE`, or `UNRESOLVED`.

No nearest-neighbor edge is promoted beyond discovery without independent evidence. Point-in-polygon proves spatial containment only; it does not prove entity identity.

## Required regression gates

- source and retained/excluded counts close arithmetically
- required fields present
- stable-ID uniqueness or explicitly adjudicated multiplicity
- no unintended row loss, duplication, or M:N multiplication
- metric/unit/parameter identity boundaries preserved
- datum incompatibility blocks cross-site comparison
- stale feeds never present as current operational truth
- null/empty geometry classified explicitly
- CRS and geometry type preserved or loss recorded
- watershed containment uses exact topological tests, not bbox membership
- extraction status negative regressions prevent source-absence illegality inference
- duplicate/edge cases preserve complete candidate sets
- source snapshot includes retrieval UTC, request/query, raw manifestation hash, schema/count metadata

## CI checkpoint

PR #228 triggered repository validation, dashboard, HAF, federation, GUI parity, CodeQL, secret-scan, and other workflows. At the first attempt, GitHub marked all jobs failed before exposing any executed job steps; job log blobs were unavailable. A targeted retry of the `validate` failed jobs was requested. Until executable CI evidence exists, CI remains `BLOCKED` rather than `PASS` and the PR remains draft/unmerged.

An independent local checkout attempt was also blocked because the execution container could not resolve `github.com`; that environment failure is not treated as evidence that the code passes or fails.

## Final states for this checkpoint

| Vector | State |
|---|---|
| Rivers series + station geometry | PASS |
| Reservoir series + station geometry | PASS |
| Rainfall station series + station geometry | PASS |
| Groundwater series + station geometry | PASS |
| Coastal series + station geometry | PASS |
| Map-first canonical AssetMap wiring | PASS |
| Fail-closed extraction classification contract | PASS |
| Federation/HAF water-monitoring capability contract | PASS |
| Restartable source snapshot tooling | PASS (implementation) / OPEN (executed watershed snapshot) |
| Watershed authoritative source identity | PASS |
| Frozen watershed manifestation + hashes | OPEN |
| Station↔watershed topology execution | OPEN |
| Physical well GIS candidate-source identity | PASS as CANDIDATE_NOT_IDENTITY |
| DRNA permit/franchise authoritative rowset | BLOCKED |
| Physical well↔permit/franchise adjudication | BLOCKED |
| Water-quality source adapters | PASS |
| Water-quality analyte-safe frontend contract | OPEN |
| GitHub CI | BLOCKED pending executable runner evidence |
| Complete certification | PROVISIONAL |

A script or CI success is necessary implementation evidence but is not itself certification. The complete certification claim requires zero material unresolved residue inside the defined scope.
