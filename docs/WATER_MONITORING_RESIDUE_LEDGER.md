# AguaYLuz Water Monitoring Residue Ledger

Snapshot date: 2026-09-04
Branch: `feature/water-monitoring-closure`
Certification target: `AGUAYLUZ WATER MONITORING CERTIFIED`

This ledger is fail-closed. A discovered source is not an identity binding; a form is not an issued authorization; a working script is not an executed source freeze; and a mergeable PR is not a certified green set.

## Passed artifacts retained

- merged PR #223 baseline
- canonical map integration using existing `AssetMap`
- metric-safe river/reservoir/rainfall/groundwater/coastal monitoring contracts
- explicit series-readiness vs geometry-readiness states
- extraction legal-state negative-inference rules
- restartable mutable-source snapshot tooling
- one-row-per-station watershed topology tooling with complete candidate preservation
- federation water-monitoring capability contract and HAF fail-closed inheritance
- analyte-safe water-quality identity contract: `site_no + parameter_code + unit`

## Watershed evidence

State: `OPEN`

Authoritative manifestation discovered:

- authority: Puerto Rico Planning Board SIGE / MiPR
- service: `MIPR/Geologia_v10_N`
- layer: `0`, `Cuencas Hidrográficas`
- service item id: `7c024f1e94a4461cb9e38334f5659aff`
- source CRS: EPSG:32161
- geometry: polygon
- service max record count: 2000
- supported query formats: JSON, geoJSON, PBF
- pagination: supported
- configured stable-ID candidates: `GlobalID`, `CUENCA_ID`

Remaining gate: execute the repository snapshot tool against the mutable service, freeze raw bytes/page manifests/SHA256/count/schema, then run exact station-to-watershed topology on that frozen manifestation. This environment could discover the service but could not create a byte-identical raw snapshot; therefore no manifestation hash is claimed.

## DRNA water authorization

State: `BLOCKED`

Authoritative semantics discovered:

1. DRNA Division de Permisos y Franquicias de Agua (DPFA) is the competent office evaluating well permits and water-franchise applications under Puerto Rico Act 136 of 1976 and the governing water-use regulation.
2. Regulation 6213 distinguishes construction permits from water franchises and requires the applicable franchise process for extraction systems, subject to its exceptions and conditions.
3. `FA-03` supplies construction-permit application requirements for a well or water intake.
4. `FA-09` supplies water-franchise application semantics, including petitioner/franchise holder, well location, withdrawal quantity, and withdrawal method.
5. The public SIGE root exposes a `DRNA` service folder, but anonymous access to that folder redirects to the SIGE login surface.
6. Public `MIPR/Permisos` exposes historical/general SuperSIP/SIP/ARPE/JP permit layers. Its `Permisos Ambientales (SuperSip)` layer contains case/project/status/adjudication/cadastre/municipality/agency/category fields, but it is not established as the exhaustive DPFA issued-franchise/permit ledger.
7. Public JCA/AAA well layers are physical/source manifestations only and remain `CANDIDATE_NOT_IDENTITY` for DRNA authorization.

Required authoritative record classes still not exhaustively bound:

- issued well/intake permit
- issued water franchise
- recognized acquired-water right
- transfer/amendment
- expiration/revocation
- enforcement/adjudicative finding

No absence from any public search may be promoted to `CONFIRMED_UNAUTHORIZED`.

## Water-quality semantics

State: `PARTIAL`

Passed:

- USGS discrete-sample ingest preserves `metric=water_quality` and `parameter_code`
- unitless values are rejected rather than relabeled
- frontend contract now refuses a chartable identity without `site_no`, `parameter_code`, and `unit`
- mixed analytes or mixed units fail the single-series certification gate
- exact selection never crosses site, parameter, or unit boundaries

Remaining gate:

- expose all intended mixed-analyte corpora through the canonical backend with a parameter-identity-aware registry/policy contract
- add the dedicated selector/chart surface using the exact identity tuple
- preserve source-specific method/QA semantics where available

Until that publication/UI gate closes, water quality remains `PARTIAL` and outside the certifiable layer set.

## CI / execution environment

State: `BLOCKED`

Observed GitHub Actions behavior on PR #228:

- validate, dashboard-build, Python matrix, typecheck, lock, geo-import and multiple federation/security workflows return failure
- validation job records expose no executed steps
- job log download returns no usable log blob
- an explicit failed-job retry reproduced the same non-evidentiary pattern
- an independent local checkout attempt failed before checkout because the execution container could not resolve `github.com`

Classification: runner/check infrastructure is not currently providing code-level failure evidence. This does not convert CI to PASS; green evidence is still required before merge.

## Certification residue

| Vector | State |
| --- | --- |
| River series + geometry | PASS |
| Reservoir series + geometry | PASS |
| Rainfall station series + geometry | PASS |
| Groundwater series + geometry | PASS |
| Coastal series + geometry | PASS |
| Map-first whole-feature binding | PASS |
| Extraction classification semantics | PASS |
| DRNA authority/regulatory semantics | PASS |
| Exhaustive issued DRNA authorization corpus | BLOCKED |
| Watershed source identity/schema discovery | PASS |
| Frozen watershed bytes/hash/count | OPEN |
| Executed station↔watershed topology | OPEN |
| Water-quality identity separation | PASS |
| Canonical mixed-analyte backend/UI publication | OPEN |
| Federation capability/HAF fail-closed contract | PASS |
| Green CI evidence | BLOCKED |
| PR #228 merge | NOT EXECUTED |
| Final certification | PROVISIONAL |

`AGUAYLUZ WATER MONITORING CERTIFIED` MUST NOT be issued while any material row above remains `OPEN`, `BLOCKED`, or `UNRESOLVED` inside the declared certification scope.
