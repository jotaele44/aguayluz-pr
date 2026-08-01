# Water Asset Graph and Impact Switchboard v0.1

## Status

Shadow-only analytical capability. It does not operate infrastructure, activate public notifications, or promote an inferred cause to confirmed status.

## Runtime contract

The existing `GET /assets` route remains backward compatible.

- `GET /assets` returns the original asset array.
- `GET /assets?impact=true&view=public` returns the versioned switchboard envelope.
- `view=operator` is disabled unless `AGUAYLUZ_OPERATOR_ASSET_VIEW_ENABLED=true`.
- Filters remain available through `type`, `search`, `impact_status`, and `municipality`.

The response binds the current `utility_assets.jsonl` corpus, the non-destructive `asset_crosswalk.jsonl` clusters, alert dependency edges, operational alerts, and the append-only monitoring incident ledger.

## Versioned schemas

The frozen v0.1 contracts are isolated from the repository's unversioned top-level schema set:

- `schemas/water-asset-graph/v0.1/water_asset_graph.schema.json`
- `schemas/water-asset-graph/v0.1/water_asset_relationship.schema.json`

The graph schema uses a local relative reference to the relationship schema so the pair remains portable and validates without network access.

## Canonicalization

1. Preserve every source record in `data/utility_assets.jsonl`.
2. Apply existing crosswalk clusters without deleting source records.
3. Group duplicate source identifiers.
4. Select the strongest representative using review status, evidence tier, confidence, geometry, and source provenance.
5. Emit one stable canonical node and retain all aliases.
6. Derive a content-addressed `baseline_id`; identical inputs produce an identical identifier.

No source asset is silently discarded. `source_record_count`, `alias_asset_ids`, and `duplicate_records_collapsed` retain the reconciliation trail.

## Provenance classes

| Class | Meaning |
|---|---|
| `public_authoritative` | Accepted T1 record with sufficient confidence |
| `public_secondary` | Public record that is useful but not authoritative enough for confirmation |
| `inferred` | Record whose placement or identity remains analytical |
| `operator_restricted` | Control-level asset whose exact public detail is withheld |
| `unresolved` | Missing, blocked, rejected, or insufficient provenance |

## Impact states

| State | Rule |
|---|---|
| `confirmed` | Exact asset binding from accepted T1 evidence |
| `suspected` | Exact lower-tier binding, or strong water-operation linkage |
| `derived` | Dependency or broad-hazard exposure; always labeled inference |
| `stale` | Active evidence older than seven days relative to the newest corpus evidence |
| `unknown` | No current evidence supports an impact state |

Confidence alone never confirms an asset. Proximity and municipio matches remain `suspected` or `derived`.

## Relationships

The graph vocabulary is frozen at:

`UPSTREAM_OF`, `DOWNSTREAM_OF`, `SUPPLIES`, `DEPENDS_ON`, `POWERED_BY`, `BACKUP_FOR`, `LOCATED_IN`, `SERVES`, `MONITORED_BY`.

Only existing relationship records and direct asset attributes are admitted. Unknown dependency vocabularies are counted as coverage gaps rather than coerced into a causal edge.

Propagation is bounded to three hops. Confidence is capped by every traversed edge and reduced by 15 points per hop. `LOCATED_IN` never propagates an outage.

## Public and operator views

Public view masks exact coordinates, names, and source references for control-level subtypes such as valves, SCADA/control points, feeder assignments, and pressure-reducing/interconnection assets.

Operator view is an explicit runtime opt-in. This repository does not treat the flag as authorization for infrastructure control; it only enables the more detailed analytical display.

## Frontend

The existing `/assets` page is upgraded to the **Asset Impact Switchboard** and remains discoverable through the sidebar. It exposes:

- impact-state totals;
- canonical inventory and deduplication counts;
- mapped assets;
- dependency edges and inference labels;
- incident/evidence timeline;
- contradiction review;
- coverage gaps;
- the full asset inventory.

The page states the baseline identifier and the shadow/no-control/no-notification boundary.
