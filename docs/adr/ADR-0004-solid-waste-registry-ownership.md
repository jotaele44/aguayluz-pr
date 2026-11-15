# ADR-0004: Agua y Luz as solid-waste (vertedero/landfill) site registry owner

- Status: Proposed
- Date: 2026-11-05
- Scope: `aguayluz-pr` registry. Cross-references hub ADR 0006, 0008 and 0009 (`thehub-pr/docs/adr/`) and `spiderweb-pr/docs/REPO_BOUNDARY.md`.

## Context

Puerto Rico's solid-waste sites (municipal vertederos, engineered landfills, transfer stations, unauthorized dumps) are the **source** end of the exposure graph this repo already models: SOURCE -> RELEASE -> PATHWAY -> RECEPTOR, with the receptors (wells, gauges, PRASA assets) ingested here.

What exists today:

- `src/aguayluz/environmental_exposure.py` defines the entity kinds `LANDFILL`, `SOLID_WASTE_FACILITY` and `DISPOSAL_SITE`.
- `config/environmental_exposure_sources.v1.json` registers the `PR_SOLID_WASTE` family; `research/environmental_exposure/source_denominator_progress.v1.json` holds it at `REGISTERED_NOT_EXHAUSTED` with no locators.
- `federation.json#source_truth.owns` named no solid-waste or environmental domain, and the environmental plane is not exported to the hub (`scripts/federation_export.py` emits only utility assets, operators, municipalities and service events). No `data/environmental_*.jsonl` files exist.
- The frozen federation GIS matrix (`docs/FEDERATION_GIS_CAPABILITY_MATRIX_v1.md`) assigns AguaYLuz "water/power/environmental infrastructure".
- `spiderweb-pr` holds three landfill-named pins at 2-3 decimal coordinates, class `INDUSTRIAL`. They are discovery seeds, not a registry.

## Decision

1. `aguayluz-pr` owns the **registry** of Puerto Rico solid-waste sites: producer-native site identity, geometry, operating and regulatory state over time, and links into the exposure graph. The owns list in `federation.json` and `config/federation_manifest.yaml` gains `solid_waste_landfill_site_registry`.
2. `aguayluz-pr` does **not** own: operator, contract and funding chains (`moneysweep-pr`); site imagery acquisition and change analysis (`spiderweb-pr`, interim, see Imagery); cross-producer identity equivalence, correlation, evidence certification and the supported viewer (`thehub-pr`).

## Precedence: hub versus producer

This is `aguayluz-pr`'s position and is **pending hub confirmation**; a producer repository cannot bind the hub.

- **Hub rules take priority where an activity crosses a repository boundary or yields a federation-level claim:** cross-producer identity equivalence (hub ADR 0009), correlation, aggregation, certification and promotion of evidence, frozen shared contracts, and the supported viewer.
- **Producer rules take priority for repo-internal activity:** the producer's own domain records and native identifiers, its ingest and analysis pipelines, and its internal schemas.
- An activity is **cross-repo** if its output leaves the repo (export), it depends on another repo's records, or it asserts equivalence or correlation between records of two repos.
- Where an Accepted hub ADR expressly reaches repo-internal activity, that ADR governs for the repository it names. This ADR does not narrow it. Hub ADR 0006 is such a case for `skywatcher-pr`: it treats producer-local provider credentials and standalone acquisition as the defect.

Basis: hub ADR 0009 limits the hub's authority to cross-producer identity equivalence and states that producers remain authoritative for their domain records; `spiderweb-pr/docs/REPO_BOUNDARY.md` assigns the hub federation orchestration and cross-producer correlation only.

## Record contract (no schema change)

| Concept | Existing contract |
|---|---|
| Site | `schemas/environmental_entity.schema.json`: `entity_kind` `LANDFILL` (engineered or municipal), `SOLID_WASTE_FACILITY` (transfer and processing), `DISPOSAL_SITE` (unauthorized dumps); `authority`, `authority_id`; `valid_from`/`valid_until`; `review_status`. ID from `derive_entity_id(kind, authority, authority_id)`. |
| Geometry | `schemas/environmental_geometry.schema.json`: `geometry_role` `SOURCE_SITE_GEOMETRY`. Coordinate precision is stated in `transformation_notes`; approximate seeds carry `review_status` `needs_review`. No new role value is needed. |
| Lifecycle | `schemas/environmental_exposure_event.schema.json`: closure as `SHUTDOWN`, `REACTIVATION`, `PERMIT_CHANGE`, `LISTING_CHANGE`, `REMEDIATION`; opening and enforcement actions as `OTHER` with `reason_raw`. |
| Links | `schemas/exposure_relationship.schema.json`: default `causal_state` `DISCOVERY_CANDIDATE`. `NAME_ONLY` and `PROXIMITY_ONLY` evidence can never promote a causal relationship. |

## Seeds and identity

Three landfill-named pins in `spiderweb-pr`'s pin registry, two GNIS "Vertedero" place names, and three USGS water-quality wells with VERTEDERO or LANDFILL in their names are **discovery candidates only**. They enter as `CANDIDATE_NOT_IDENTITY` through a frozen, hash-pinned import; there is no cross-repo code import. Equivalence between a `spiderweb-pr` pin and an `aguayluz-pr` site is adjudicated by the hub (hub ADR 0009); names, coordinates and proximity create candidates only.

## Export

Landfill sites are exported as `entity_type` `landfill_site`. The hub entity schema types `entity_type` as a free string and hub schemas are frozen, so no hub schema change is required. This ADR adds landfill sites only; exporting the wider environmental plane is a separate change.

## Imagery

Not owned here. A per-site satellite timeline is `spiderweb-pr`'s deliverable, and dated scenes ride hub `observations` rows (hub ADR 0008 precedent), marked provisional.

Hub ADR 0006 (Accepted) moves satellite-provider access, credentials and imagery caching into the hub, and the hub currently has contracts but no acquisition runtime. That ADR names `thehub-pr` and `skywatcher-pr`, not `spiderweb-pr`. Interim position: `spiderweb-pr` acquisition is repo-internal and its exported observations are provisional until hub certification. Trigger to revisit: the hub acquisition runtime ships.

## Consequences

- The `PR_SOLID_WASTE` denominator still has to be discovered and frozen; family presence is not exhaustion and `completeness_claimed` stays `false`.
- The `PR_DRNA` authority label on that family needs confirmation against the actual solid-waste authority.
- Adding a data ingest script later triggers the README docs-sync coupling.

## Open items

1. Hub confirmation of the Precedence rule (a hub-side ADR clarification would make it binding).
2. Whether hub ADR 0006 reaches `spiderweb-pr`'s `imagery/` package.
3. `config/federation_manifest.yaml` says it mirrors `AGUAYLUZ_PR_SKILL.md`, which is not in this repository; that mirror cannot be updated here.
4. `docs/adr/` already contains two `ADR-0003-*` files. Not renumbered here.
