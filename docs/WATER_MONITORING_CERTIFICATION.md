# AguaYLuz Water Monitoring Certification

## Current state

`PROVISIONAL` — the public console shell and existing live-series contracts are integrated, but the defined certification scope is not closed.

## Certification claim

`AGUAYLUZ WATER MONITORING CERTIFIED` may be issued only when every in-scope layer is fully classified and there is zero material unresolved residue inside the claim.

## A — Public monitoring experience

Required: rivers, reservoirs, rainfall, groundwater, coastal water, search/filter controls, map geometry, freshness, source provenance, metric/unit identity, datum handling, stale-source behavior, historical context, and incident linkage.

Existing metric-safe charts remain canonical for time-series rendering. They must not aggregate across incompatible metric, unit, parameter-code, site, or datum identities.

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

`CONFIRMED_UNAUTHORIZED` requires an authoritative enforcement or adjudicative source. Source absence, proximity, name similarity, parcel coincidence, or count equality cannot establish illegality or identity.

## C — Hydrologic digital twin

Canonical topology:

`watershed → subwatershed → river_segment → gauge → reservoir → intake → treatment_asset → distribution_context`

and

`aquifer → recharge_zone → well/spring → withdrawal → watershed/coastal receiving context`.

Edges must preserve provenance and may be `AUTHORITATIVE`, `CERTIFIED_GEOMETRIC`, `DERIVED_TOPOLOGICAL`, `CANDIDATE`, or `UNRESOLVED`.

No nearest-neighbor edge is promoted beyond discovery without independent evidence.

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
- watershed containment uses topological tests, not bbox membership
- extraction status negative regressions prevent source-absence illegality inference
- duplicate/edge cases preserve complete candidate sets
- source snapshot includes retrieval UTC, request/query, raw manifestation hash, schema/count metadata

## Final states

Each layer must end as `PASS`, `FAIL`, `OPEN`, `BLOCKED`, `PROVISIONAL`, `NONCANONICAL`, `CANDIDATE_NOT_IDENTITY`, `UNRESOLVED`, or `SUPERSEDED`.

A script or CI success is necessary evidence for implementation quality but is not itself certification.
