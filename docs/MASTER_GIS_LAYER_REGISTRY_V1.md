# Master GIS Layer Registry v1 — Certification Contract

This registry is a **planned taxonomy**, not a claim of complete geographic, temporal, source, or operational coverage. Its authoritative machine-readable contract is `config/master_gis_layer_registry.v1.json`.

## Bounded source enumeration
For each atomic layer, record authority, exact dataset URL, retrieval scope/query, retrieved timestamp, source revision, raw SHA-256, geometry source, CRS, licensing/access constraints, inclusion/exclusion rule and refresh cadence. Record source / retained / excluded / unresolved counts with delta zero. An empty result is not evidence of no contamination.

## Scope
- Main island, Vieques and Culebra: land and jurisdictionally relevant coastal/marine features.
- Preserve true polygon, line and point geometry, including multipart and offshore geometry; no synthetic polygons or inferred restrictions.
- A site boundary is not a contaminant plume; UXO and legal closures are distinct from sampled contamination.
- Historical and expired restrictions remain historical, never active by default.
- Offshore areas require an explicit jurisdiction and authoritative spatial boundary.

## Evidence firewall
- OBSERVED: official designations, laboratory observations, issued restrictions and recorded events, with provenance.
- COMPUTED: derived spatial intersections or network exposures, with method and dependencies; never causal by proximity.
- HYPOTHETICAL: sandbox scenario outputs, isolated from operational alerts and federation observed streams.
- UNRESOLVED: ambiguous, missing, stale or conflicting source evidence. Unknown != safe.

## Implementation path
1. Freeze exact baseline SHA and snapshot existing MapLibre, hazard plane, alerts and federation contracts.
2. Enumerate atomic layers and authoritative source manifestations, independently for land and marine.
3. Validate identity, source arithmetic, CRS, geometry topology and temporal validity.
4. Add a versioned GeoJSON/tiles endpoint and layer-group controls to the existing `MapPage.jsx` / `AssetMap.jsx`; reuse canonical map.
5. Add provenance-aware inspection cards and candidate exposure analysis.
6. Isolate scenarios from source records, active restrictions and operational alert promotion.
7. Execute positive and negative regression tests, accessibility/rendered QA and TheHub federation consumer checks against the exact candidate commit.

## Release rule
Default **BLOCKED**. A registry file alone does not pass any runtime gate. No deployment, merge, certification or promotion until independent evidence exists for every applicable gate and unresolved material within the certified scope is zero. Historical PASS cannot certify new source manifestations or a later commit.
