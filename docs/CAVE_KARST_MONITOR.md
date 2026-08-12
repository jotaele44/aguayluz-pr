# Cave and Karst Monitor

## Status

**Phase:** additive core implementation with a Río Camuy pilot  
**Registry coverage:** pilot only; the schema and ID namespace are statewide-ready  
**Public exact cave coordinates:** prohibited by default  
**Current pilot state:** `closed`, observed 2026-08-04T00:44:00Z

This module treats a cave system as a natural–operational hybrid. It does not force caves into `utility_asset.schema.json`, which is limited to water, wastewater, power, telecom, and fuel assets. Instead, cave/karst assets receive a dedicated schema and connect to AguaYLuz entities through typed graph edges.

## Canonical files

| File | Purpose |
|---|---|
| `schemas/cave_karst_asset.schema.json` | Operational, hydrologic, environmental, infrastructure, review, and disclosure contract |
| `schemas/cave_karst_source.schema.json` | Source registry and content-hash provenance |
| `schemas/cave_karst_edge.schema.json` | Typed links to cave assets, utility assets, natural features, monitoring sites, watersheds, municipalities, operators, and sources |
| `schemas/cave_karst_status_event.schema.json` | Append-only status and infrastructure history |
| `schemas/cave_karst_observation.schema.json` | Metric/value observations across the four monitoring dimensions |
| `data/cave_karst_*.jsonl` | Canonical pilot registry |
| `src/aguayluz/cave_karst.py` | Validation, hash-chain verification, state materialization, contradiction detection, and alert generation |
| `scripts/validate_cave_karst_registry.py` | Deterministic validation receipt |
| `tests/test_cave_karst_monitor.py` | Contract, history, alert, and disclosure tests |

## Asset identity

Canonical IDs use `AYL_KARST_<STABLE_UPPERCASE_TOKEN>`.

| Asset ID | Kind | Review |
|---|---|---|
| `AYL_KARST_CAMUY_PARK` | park | accepted |
| `AYL_KARST_CAMUY_CUEVA_CLARA` | cave | needs review |
| `AYL_KARST_CAMUY_RIVER_SYSTEM` | underground river | needs review |
| `AYL_KARST_CAMUY_VISITOR_ACCESS` | access infrastructure | accepted |

Component-level records are deliberately less confident than the park-level record because the current source states the park-wide condition and does not independently certify every internal component.

## Monitoring dimensions

### Operational

The state set is `open`, `closed`, `partially_open`, `restricted`, `maintenance`, or `unknown`. Public access, operator, reservations, closure reason, expected reopening, and status observation time remain separate fields. An old reopening announcement cannot silently override a newer closure observation.

### Hydrologic

Hydrologic fields capture role, known waterbody/watershed identifiers, flood sensitivity, surface-water connection, monitoring coverage, and latest observation time. Connections remain `unknown` or `needs_review` unless directly supported.

### Environmental

The schema records protected designations, habitat sensitivity, water-quality monitoring, and bounded hazard categories. It does not expose sensitive habitat coordinates.

### Infrastructure

The schema supports access roads, trails, stairs, railings, lighting, trams, gates, signage, sensors, emergency access, and verified utility dependencies. The pilot contains **zero utility-asset links** because no canonical AguaYLuz utility IDs were verified during this pass.

## Graph and provenance integration

`cave_karst_edge` bridges to the existing AguaYLuz graph. The target node can be another cave asset, a canonical utility asset, a natural feature, monitoring site, watershed, municipality, operator, or source record.

Every asset, edge, event, and observation carries source references, evidence tier, confidence, and review status. Sources have deterministic SHA-256 content fingerprints. Status events additionally form a global append-only hash chain.

## Status history and supersession

The Río Camuy pilot preserves three accepted status assertions:

1. DRNA system-wide closure notice effective 2017-09-05.
2. Government reopening notice effective 2021-03-24.
3. Current closure observation retrieved 2026-08-04.

The 2026 observation supersedes the 2021 open state without inventing the exact date on which the park closed again. The materialized state is therefore `closed`, while historical rows remain immutable.

## Alert rules

| Rule | Severity |
|---|---:|
| Public park/cave/access asset is closed | 3 |
| Public park/cave/access asset is restricted, partial, or in maintenance | 2 |
| Operational status is missing or older than the configured freshness window | 2 |
| High flood sensitivity while open or partially open | 4 |
| Conflicting accepted status intervals | 3 |

Alerts are evidence summaries. They do not authorize entry, emergency response, or field activity.

## Río Camuy pilot adjudication

### Current operational state

The current official destination page says that the park is closed until further notice. This is treated as a T2 operational source because Discover Puerto Rico is an official destination organization but not the DRNA park custodian.

### Historical reopening

The Puerto Rico Tourism Company announced appointment-only visits beginning 2021-03-24. That record is retained as T1 historical evidence and explicitly superseded for current-state materialization.

### Infrastructure signal

Puerto Rico's procurement portal listed a 2026 solicitation for repairs and acquisitions at the park as cancelled. The observation is stored as `repair_procurement_status=cancelled`. It is **not** promoted into a claim that repairs were completed, stopped, or absent under other contracts.

## Source register

- DRNA closure notice: `https://www.drna.pr.gov/noticias/recursos-naturales-anuncia-cierre-de-instalaciones-por-huracan-irma/`
- Puerto Rico Tourism Company reopening notice: `https://tourism.pr.gov/2021/03/17/se-acerca-la-reapertura-del-parque-de-las-cavernas-de-camuy/?lang=es`
- Discover Puerto Rico current destination page: `https://www.discoverpuertorico.com/es/articulo/explora-el-parque-de-las-cavernas-de-camuy`
- ASG procurement notice: `https://subastas.pr.gov/Pages/aviso.aspx?itemID=13084`

## Coordinate and safety policy

The pilot uses `public_generalized` disclosure and null latitude/longitude for all cave records. A future statewide build must separate public visitor geography, generalized research geography, and restricted ecological, archaeological, or safety-sensitive coordinates.

No inferred passage geometry, hidden entrance, subsurface route, or utility connection may be promoted from proximity alone.

## Validation

```bash
python scripts/validate_cave_karst_registry.py
pytest -q tests/test_cave_karst_monitor.py
```

The validator checks all five JSON Schemas; unique IDs; referential integrity; allowed status transitions; append-only ordering and hash-chain integrity; supersession-aware contradiction detection; and current-state materialization.

## Remaining statewide work

This PR does **not** claim a complete Puerto Rico cave census. Statewide promotion requires a separate evidence-acquisition pass covering DRNA protected areas, USGS/GNIS features, hydrologic monitoring, municipal ownership, public access, infrastructure dependencies, and restricted-coordinate adjudication. Candidate records must remain `statewide_candidate` and `needs_review` until cross-source corroboration is complete.
