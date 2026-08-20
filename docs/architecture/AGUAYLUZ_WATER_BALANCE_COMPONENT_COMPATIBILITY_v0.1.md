# AguaYLuz Water-Balance Component Compatibility Matrix v0.1

Pinned base: `main@17c843595b5cdfbcef4e5f7b1ac6c662092e335d`

## Disposition vocabulary

- **PRESERVE** — remains authoritative in its current role.
- **ADAPT** — project into the canonical ledger without rewriting the source.
- **MERGE** — reconcile overlapping concepts after explicit adjudication.
- **DEPRECATE** — stop creating new records only after a replacement and migration receipt exist.
- **REVIEW** — unresolved overlap, stale WIP, or insufficient contract evidence.

## Current-main components

| Component | Existing role | Compatibility finding | Disposition | Canonical target |
|---|---|---|---|---|
| `schemas/utility_asset.schema.json` | Static utility assets | Broad utility type and subtype model; insufficient hydrologic roles and topology semantics | ADAPT | `Asset` |
| `data/utility_assets.jsonl` | Source-level asset corpus | Must retain source IDs and aliases; likely duplicates across providers | PRESERVE + ADAPT | asset crosswalk and canonical assets |
| `schemas/asset_crosswalk.schema.json` | Asset identity reconciliation | Useful identity layer; cannot imply hydraulic connectivity | PRESERVE | canonical identity lineage |
| `schemas/monitoring_reading.schema.json` | Routine daily readings | Date-only, one value, closed metric enum; lacks interval, method, uncertainty, freshness and datum objects | PRESERVE + ADAPT | `WaterObservation` |
| `schemas/service_event.schema.json` | Discrete operational/service events | Event truth is distinct from physical quantity accounting | PRESERVE | contextual event linkage |
| `schemas/alert_event.schema.json` | Analytical/operational alerts | Must consume balance findings only after separate promotion policy | PRESERVE | downstream alert candidate |
| `schemas/alert_gap.schema.json` | Monitoring gaps | Directly reusable for missing balance terms and coverage gaps | ADAPT | balance gap |
| `schemas/alert_dependency_edge.schema.json` | Dependency relations | Dependency is not hydraulic flow; relation types must remain separated | PRESERVE + ADAPT | contextual edge, not flow by default |
| `schemas/source_manifest.schema.json` | Source provenance | Required parent lineage for all observations and transformations | PRESERVE | `Lineage` |
| `schemas/review_queue.schema.json` | Human adjudication | Reusable for contradictions and promotion review | PRESERVE | review disposition |
| `schemas/integration_report.schema.json` | Integration receipts | Reusable for later shadow migration receipts | PRESERVE | migration receipt |
| `scripts/ingest_water.py` | Water-source ingestion | Existing adapter output must be projected, not rewritten | ADAPT | observation projection |
| `scripts/ingest_usgs_water.py` | USGS water ingestion | Preserve source parameter and provisional semantics | ADAPT | observation projection |
| `scripts/ingest_usgs_levels.py` | Reservoir/level ingestion | Elevation and storage percent cannot be treated as volume without curve lineage | ADAPT | storage observation |
| `scripts/ingest_usgs_groundwater.py` | Groundwater daily values | Level is not storage; pumping/static and datum semantics remain explicit | ADAPT | groundwater observation |
| `scripts/ingest_usgs_samples.py` | Water-quality samples | Contextual constraint; not a volumetric balance term | PRESERVE + ADAPT | quality observation |
| `scripts/ingest_neon.py` | Environmental observations | Site-specific environmental context; hydrologic representativeness required | ADAPT | contextual observation |
| `scripts/ingest_neon_products.py` | Product-derived observations | Derived method and product lineage required | ADAPT | modeled/derived observation |
| `scripts/ingest_noaa_tides.py` | Coastal water level | Relevant to boundary conditions; not direct reservoir or aquifer volume | ADAPT | boundary observation |
| `scripts/ingest_nws_alerts.py` | Weather hazards | Event context only; rainfall quantity must come from a precipitation product | PRESERVE | contextual event |
| `scripts/refresh.py` | Scheduling/orchestration | No balance execution is added in design v0.1 | PRESERVE | future shadow schedule only |
| `scripts/build_alerts.py` | Derived alerts | Must not consume balance residuals before promotion policy exists | PRESERVE | later downstream consumer |
| `src/aguayluz/water_alerts.py` | Hydrologic alert logic | Statistical proxies must remain distinct from physical mass-balance claims | PRESERVE | contextual anomaly evidence |
| `server/backend/monitoring_quality.py` | Quality assessment | Candidate source for quality flags; requires mapping rather than duplication | ADAPT | `Quality` |
| `server/backend/monitoring_incident_ledger.py` | Append-only incident history | Remains incident truth; no residual-created confirmed incidents | PRESERVE | incident linkage |
| `server/backend/monitoring_alert_operations.py` | Alert operations | Remains downstream of validation gates | PRESERVE | downstream consumer |
| `server/backend/water_disruption.py` | Candidate validation and incident lifecycle | Truth strength and append-only lifecycle remain authoritative | PRESERVE | incident promotion boundary |
| `server/backend/water_disruption_api.py` | Water-disruption API | No balance route added in v0.1 | PRESERVE | future read-only surface |
| `scripts/federation_export.py` | Federation export | Water-balance products denied until a later export ballot | PRESERVE | later explicit mapping |
| `federation.json` | Federation capability contract | No design-only capability activation | PRESERVE | no change |
| `.federation/gui-capabilities.json` | GUI parity map | No GUI route or public symbol added | PRESERVE | no change |
| `dashboard/src/components/IncidentOperationsConsole.jsx` | Incident GUI | Balance findings must not appear as confirmed incidents | PRESERVE | future read-only link |

## Open pull-request and WIP components

| PR / branch | Candidate capability | Overlap or risk | Disposition |
|---|---|---|---|
| #101 | Canonical water asset graph and impact switchboard | Strong overlap with canonical Asset and contextual graph; hydraulic flow evidence remains incomplete | REVIEW, then MERGE concepts selectively |
| #96 | Environmental provider registry | Provider registration can be mistaken for observation coverage | REVIEW; map only to source coverage |
| #109 | USGS field measurements, peaks, NHC | Overlaps #116 and contains additional non-USGS storm scope | REVIEW; adjudicate record and parameter ownership |
| #116 | Ten-category USGS coverage contracts | Coverage registry is not measured water movement | REVIEW; preserve coverage truth separately |
| #118 | Laguna Cartagena control plane | Candidate pilot with synchronized-balance rules; remains unmerged | REVIEW; pilot mapping after adjudication |
| #114 | Cave and karst registry | Karst context is important but does not prove flow paths | REVIEW; contextual assets and edges only |
| #115 | Cave/karst API and GUI | Stacked dependency and privacy requirements | REVIEW; no dependency in v0.1 |
| #104 | Federation export/validation rescue WIP | May contain stale or superseded schema changes | REVIEW for unique patches only |
| #105 | Water-intelligence tests/fixtures rescue WIP | Possible fixture reuse; unknown current-main compatibility | REVIEW for unique test cases only |
| #106 | Presync data and water-intel WIP | Large data change and mixed concerns | REVIEW; never wholesale merge through this vector |
| #107 | USGS water ingestion rescue WIP | Likely superseded by main and #109/#116 | REVIEW for patch identity and unique behavior |
| #108 | Federation conformance rescue WIP | Unrelated history surfaced by rescue branch | REVIEW; no architecture dependency |

## Duplicate and contradiction classes

| Class | Example | Control |
|---|---|---|
| Asset duplication | Same well represented by provider-specific IDs | Alias/crosswalk lineage; no coordinate-only merge |
| Observation duplication | Same source value emitted by two adapters | Source-equivalence key and source record hash |
| Concept collision | Dependency edge interpreted as hydraulic flow | Edge semantic class and balance eligibility gate |
| Metric inversion | Groundwater elevation above datum mixed with depth below land surface | Datum/direction metadata and incompatible-series rejection |
| Temporal collision | Date-only value aligned to hourly telemetry | Precision-preserving synchronization gate |
| Storage collision | Reservoir elevation, percent full, and volume treated as independent storage quantities | Stage-storage transformation lineage and supersession |
| Coverage collision | Registered provider treated as active monitoring | Separate provider, endpoint, observation, and current-condition coverage states |
| Event/quantity collision | Service interruption treated as measured loss volume | Keep event truth and quantity accounting separate |
| Residual/proof collision | Open residual presented as a confirmed leak or illegal well | Cause-attribution ladder and incident validation boundary |

## Orphan and gap findings

1. Current main lacks a canonical volumetric ledger with explicit boundary ownership.
2. Current routine readings lack interval timestamps, uncertainty objects, freshness objects, and transformation lineage.
3. Authoritative treatment-plant intake/output, tank telemetry, pressure-zone meters, valve states, and interconnection flows remain external gaps.
4. Private-well and industrial-pumping completeness remains unresolved.
5. Reservoir stage-storage curves and sedimentation versions are not represented as first-class transformations.
6. Existing asset dependency graphs cannot be assumed to encode hydraulic topology.
7. Current federation contracts do not authorize water-balance residual exports.
8. Open PRs #109, #116, and #118 contain useful but overlapping acquisition/control-plane concepts that require explicit merge adjudication.

## Zero-silent-migration rule

Every existing source concept must receive exactly one of `PRESERVE`, `ADAPT`, `MERGE`, `DEPRECATE`, or `REVIEW`. A later implementation may not rename, merge, delete, or reinterpret a record without a machine-readable mapping, source and target hashes, row counts, contradiction counts, and rollback instructions.