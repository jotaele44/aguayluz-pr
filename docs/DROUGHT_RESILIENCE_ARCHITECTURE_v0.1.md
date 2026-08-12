# Drought and Water Resilience Architecture v0.1 — P0

**Status:** design-only reference core  
**Implementation base:** `main@ed75d9f48f385c0dfcbf7fa015f46ff2e2bf7387`  
**Runtime state:** inactive; no API, GUI, scheduler, export, alert activation, or data migration

## Mission

Extend AguaYLuz-PR beyond asset inventory toward provenance-bound water-state and drought/resilience analysis without absorbing generic hydrography, subsurface inference, or unverified operating thresholds.

## P0 contracts

1. `DroughtState` — exactly one of meteorological, hydrological, agricultural, or socioeconomic drought for one geography/date.
2. `WaterSupplySystem` — declared source→intake/well→treatment→storage→distribution→demand topology; every edge requires evidence binding.
3. `RapidOnsetAssessment` — deterministic rate-of-change assessment against an explicit, source-bound rule.

## Epistemic invariants

- Meteorological drought does not imply hydrological drought.
- Hydrological drought does not imply agricultural or socioeconomic drought.
- No class is synthesized from another without an independent class-specific observation/methodology.
- A rapid-decline result is an analytical trigger, not an official drought declaration.
- Rapid-onset thresholds are caller supplied and must have `source_ref`; the core contains no hidden Puerto Rico operating threshold.
- Proximity, shared municipality, same/similar name, count equality, and nearest-neighbor discovery do not establish water-system topology.
- Every supply-system edge must carry `binding_ref`; unresolved candidate relations remain unresolved rather than being promoted.
- Crosswalk to `alert_event.schema.json` is `draft` + `needs_review`; P0 never activates an alert.
- No asset is linked by proximity in the P0 crosswalk.
- Generic NHD/NHDPlus flowlines, catchments, wetlands, karst geometry, and inferred subsurface connectivity remain outside this P0 scope.

## Compatibility with existing AguaYLuz

| Existing component | P0 disposition |
|---|---|
| `monitoring_reading.schema.json` | Input-compatible indicator provenance; no schema mutation |
| `alert_event.schema.json` | Reused unchanged via draft crosswalk |
| `water_alerts.py` | Unchanged; current statistical tail proxies remain separate |
| resource-balance v0.1 | Complementary; supply topology may later become a water-domain topology source after independent adjudication |
| utility assets | Referenced by stable IDs only when independently bound |
| GUI parity | No runtime-discovered capability in P0; all code remains under `research/` and is not a user workflow |

## Rapid-onset algorithm

Given observations for one metric and an explicit `TrajectoryRule`:

1. filter to that metric;
2. discard malformed dates/values;
3. sort deterministically by date;
4. require configured point count and elapsed-day denominator;
5. calculate endpoint signed rate `(last - first) / elapsed_days`;
6. orient the rate to the configured concerning direction;
7. compare against the externally supplied threshold;
8. return `not_assessable` when denominator requirements fail.

P0 deliberately does not choose a climatological window, percentile, SPI/SPEI threshold, reservoir control level, groundwater trigger, or socioeconomic shortage trigger. Those require authoritative source acquisition and methodology certification.

## Alert crosswalk

A class-specific `DroughtState` can be projected into the existing alert contract only as a candidate:

- `module_id=HYDRO_OPS`
- `event_type=hazard`
- `status=draft`
- `review_status=needs_review`
- no automatic asset linkage
- validation note states that no cross-class inference or official declaration is implied

This proves contract compatibility without changing production alert semantics.

## Promotion gates

Runtime promotion requires:

1. authoritative precipitation/streamflow/reservoir/groundwater source inventory;
2. method-specific rules with frozen provenance and version identifiers;
3. historical 2014–2016 regression episode with complete denominator accounting;
4. class-specific positive and negative regression cases;
5. adjudicated water-supply topology for the promoted pilot system;
6. exact-current-main reconciliation with resource-balance and existing water-alert modules;
7. API/GUI/client state/read-only workflow plus provenance/freshness/error surfaces;
8. `.federation/gui-capabilities.json` update and E2E GUI parity evidence;
9. federation-export contract approval before downstream publication;
10. separate activation ballot for any production alert generation.

## Deferred P1/P2 contracts

- `WaterBalanceSnapshot`
- `SourceDependencyProfile`
- `DroughtEpisode`
- `DroughtResponseArtifact`
- `WaterDemandIndicator`
- `RainwaterHarvestingAsset`
- watershed-response derived features supplied cross-repository rather than generic hydrography ingest

## Certification scope

P0 can certify schema behavior, deterministic rate assessment, topology fail-closed invariants, and non-activating alert-contract compatibility. It cannot certify a current Puerto Rico drought state, an official rapid-onset threshold, a complete AAA hydraulic topology, or any 2014–2016 institutional-memory claim.
