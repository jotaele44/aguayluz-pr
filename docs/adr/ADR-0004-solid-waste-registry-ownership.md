# ADR-0004: Agua y Luz as solid-waste (vertedero/landfill) site registry owner

- Status: Proposed
- Date: 2026-11-05
- Last amended: 2026-11-23 (statements corrected against the repository and the cited sources; see git history)
- Scope: `aguayluz-pr` registry. Cross-references hub ADR 0006, 0008 and 0009 (`thehub-pr/docs/adr/`) and `spiderweb-pr/docs/REPO_BOUNDARY.md`.

## Context

Puerto Rico's solid-waste sites (municipal vertederos, engineered landfills, transfer stations, unauthorized dumps) are the **source** end of the exposure graph this repo already models: SOURCE -> RELEASE -> PATHWAY -> RECEPTOR, with the receptors (wells, gauges, PRASA assets) ingested here.

What existed when this ADR was proposed (2026-11-05):

- `src/aguayluz/environmental_exposure.py` defines the entity kinds `LANDFILL`, `SOLID_WASTE_FACILITY` and `DISPOSAL_SITE`.
- `config/environmental_exposure_sources.v1.json` registers the `PR_SOLID_WASTE` family; `research/environmental_exposure/source_denominator_progress.v1.json` holds it at `REGISTERED_NOT_EXHAUSTED` with no locators.
- `federation.json#source_truth.owns` named no solid-waste or environmental domain, and the environmental plane is not exported to the hub (`scripts/federation_export.py` emits only utility assets, operators, municipalities and service events). No `data/environmental_*.jsonl` files exist.
- The frozen federation GIS matrix (`docs/FEDERATION_GIS_CAPABILITY_MATRIX_v1.md`) assigns AguaYLuz "water/power/environmental infrastructure".
- `spiderweb-pr` holds three landfill-named pins at 2-3 decimal coordinates, class `INDUSTRIAL`. They are discovery seeds, not a registry.

State since then (2026-11-23): the registry exists. `scripts/ingest_solid_waste_registry.py` populates `data/environmental_entities.jsonl`, `data/environmental_geometries.jsonl` and `data/environmental_exposure_events.jsonl`; `scripts/federation_export.py` exports the accepted landfill sites as `landfill_site`; `federation.json` and `config/federation_manifest.yaml` list `solid_waste_landfill_site_registry`; and `research/environmental_exposure/source_denominator_progress.v2.json` (as of 2026-11-15) holds `PR_SOLID_WASTE` at `PARTIAL_BOUNDED_FEDERAL_SOURCES`.

## Decision

1. `aguayluz-pr` owns the **registry** of Puerto Rico solid-waste sites: producer-native site identity, geometry, operating and regulatory state over time, and links into the exposure graph. The owns list in `federation.json` and `config/federation_manifest.yaml` now lists `solid_waste_landfill_site_registry`.
2. `aguayluz-pr` does **not** own: operator, contract and funding chains (`moneysweep-pr`); site imagery acquisition and change analysis (`spiderweb-pr`, interim, see Imagery); cross-producer identity equivalence, correlation, evidence certification and the supported viewer (`thehub-pr`).

## Precedence: hub versus producer

This is `aguayluz-pr`'s position and is **pending hub confirmation**; a producer repository cannot bind the hub.

- **Hub rules take priority where an activity crosses a repository boundary or yields a federation-level claim:** cross-producer identity equivalence (hub ADR 0009), correlation, aggregation, certification and promotion of evidence, frozen shared contracts, and the supported viewer.
- **Producer rules take priority for repo-internal activity:** the producer's own domain records and native identifiers, its ingest and analysis pipelines, and its internal schemas.
- An activity is **cross-repo** if its output leaves the repo (export), it depends on another repo's records, or it asserts equivalence or correlation between records of two repos.
- Where an Accepted hub ADR expressly reaches repo-internal activity, that ADR governs for the repository it names. This ADR does not narrow it. Hub ADR 0006 is such a case for `skywatcher-pr`: it treats producer-local provider credentials and standalone acquisition as the defect.

Basis: hub ADR 0009 limits the hub's authority to cross-producer identity equivalence and states that producers remain authoritative for their domain records; `spiderweb-pr/docs/REPO_BOUNDARY.md` says `spiderweb-pr` does not own federation orchestration or cross-producer correlation, and names the hub as the owner of the first and, with the downstream PRIIS consumer, of the second.

## Record contract (no schema change)

| Concept | Existing contract |
|---|---|
| Site | `schemas/environmental_entity.schema.json`: `entity_kind` `LANDFILL` (engineered or municipal), `SOLID_WASTE_FACILITY` (transfer and processing), `DISPOSAL_SITE` (unauthorized dumps); `authority`, `authority_id`; `valid_from`/`valid_until`; `review_status`. ID: an LMOP landfill uses `derive_entity_id(kind, authority, authority_id)`; an ECHO source record uses `echo_entity_id(registry_id)`, which hashes only the authority and the FRS RegistryID. The kind inferred from an ECHO facility name or SIC/NAICS code is a `needs_review` attribute and never part of the id, so a later reclassification cannot re-key the record. |
| Geometry | `schemas/environmental_geometry.schema.json`: `geometry_role` `SOURCE_SITE_GEOMETRY`. `transformation_notes` states what the source does and does not say about datum and precision (LMOP publishes neither, and the note says so); coordinates whose collection method the source does not state carry `review_status` `needs_review` (the ECHO facility coordinates). The spiderweb pins are held as bindings in the receipts, not as geometry rows. No new role value is needed. |
| Lifecycle | `schemas/environmental_exposure_event.schema.json`: closure as `SHUTDOWN`, `REACTIVATION`, `PERMIT_CHANGE`, `LISTING_CHANGE`, `REMEDIATION`; opening and enforcement actions as `OTHER` with `reason_raw`. |
| Links | `schemas/exposure_relationship.schema.json`: `causal_state` is required and has no default; `DISCOVERY_CANDIDATE` marks a lead. `validate_relationship` rejects a causal predicate at a promoted state (`ANALYTICALLY_SUPPORTED`, `ATTRIBUTION_SUPPORTED`, `AUTHORITATIVELY_ATTRIBUTED`) when its evidence is discovery-only (`NAME_ONLY`, `PROXIMITY_ONLY` and the other discovery-only classes). Candidate links in the registry receipts are bindings with `adjudication_state` `CANDIDATE_NOT_IDENTITY`, not exposure relationships. |

## Seeds and identity

Three landfill-named pins in `spiderweb-pr`'s pin registry and three USGS water-quality wells with VERTEDERO or LANDFILL in their names are **discovery candidates only**. Two GNIS "Vertedero" place names were also found; they are recorded as rejected name-only seeds, because GNIS classes them as Populated Places, not waste sites. The three pins come from one local compilation package (`Spiderweb_Package+GapClosure`, layer `Normalized_Master`; records SW002520, SW002523 and SW003453). Their coordinates are already stated at two to three decimals in that source, and the source records no upstream agency, URL or date, so a pin is a name and an approximate location, nothing more. The pin registry labels them evidence tier T2; the recorded provenance supports no more than a compiled secondary dataset (T4). They enter as `CANDIDATE_NOT_IDENTITY` through a frozen import pinned to the `spiderweb-pr` commit that holds the pin registry (the receipts record the repository, path and commit, not a byte hash); there is no cross-repo code import. Equivalence between a `spiderweb-pr` pin and an `aguayluz-pr` site is adjudicated by the hub (hub ADR 0009); names, coordinates and proximity create candidates only.

## Export

Landfill sites are exported as `entity_type` `landfill_site`. The hub entity schema types `entity_type` as a free string and hub schemas are frozen, so no hub schema change is required. This ADR adds landfill sites only; exporting the wider environmental plane is a separate change.

## Enforcement context

EPA enforcement history for the registry's sites is carried as context, not as site data. The ECHO case service is pulled for the whole state and filtered locally, because it silently drops any filter it does not know; its state filter is proven to work (a nonsense state returns nothing, and the filtered count is below the unfiltered total) before a pull is trusted. Cases that concern landfills are kept as RAW rows (the full row as served); the facility reports are reduced to a per-statute summary and labelled as derived, not raw, because the full responses are frozen by hash in the receipts and not committed. Cases are linked to sites as `CANDIDATE_NOT_IDENTITY` bindings: by name (whole-municipality-name containment), or, where an ECHO facility report lists the case number among its own source ids, by that id, to the ECHO record only. A name link is never promoted to an id link, and nothing is created from a case as an entity, geometry or event, because that would assert an identity a name cannot support. A municipality named in a case that has no LMOP site is recorded as a registry-gap lead in the receipts, never as a site. The ledger states what is not covered: places spelled differently, unnamed rows, and the state agency's own records (ECHO carries only some state-led actions). The result stays OPEN.

## Imagery

Not owned here. A per-site satellite timeline is `spiderweb-pr`'s deliverable, and dated scenes ride hub `observations` rows (hub ADR 0008 precedent), marked provisional.

Hub ADR 0006 (Accepted) moves satellite-provider access, credentials and imagery caching into the hub, and the hub currently has contracts but no acquisition runtime. That ADR names `thehub-pr` and `skywatcher-pr`, not `spiderweb-pr`. Interim position: `spiderweb-pr` acquisition is repo-internal and its exported observations are provisional until hub certification. Trigger to revisit: the hub acquisition runtime ships.

## Consequences

- The `PR_SOLID_WASTE` denominator is only partly frozen (`PARTIAL_BOUNDED_FEDERAL_SOURCES`): the EPA LMOP (32 rows) and ECHO (16 rows) sources and the EPA enforcement context are frozen. Still open: the Puerto Rico solid-waste authority's own site list, unauthorized dumps, and the state agency's own enforcement records. Family presence is not exhaustion and `completeness_claimed` stays `false`.
- The `PR_DRNA` authority label on that family is supported. The Inspector General's examination OIG-E-22-018 (21 June 2022) records that the reorganization plan executed by Ley Núm. 171-2018 transfers and consolidates the powers and functions of the Junta de Calidad Ambiental, the Autoridad de Desperdicios Sólidos and the national parks program into DRNA, and that, by the Ley's substitution clause (Sección 92), any reference to the Junta is read as a reference to DRNA as its successor. The text of DRNA's proposed Title V permit for El Coquí Landfill names DRNA as the issuing authority and refers to "la otrora Junta de Calidad Ambiental, ahora Departamento de Recursos Naturales y Ambientales"; it is an unsigned draft (final-issue date `[Fecha]`, signature `[Firma]`, a signature line reading "de 2025"). Not established: that DRNA's landfill-facility permit records sit in one office (the permit read is an air permit), or, outright, that the Autoridad was dissolved; the same report twice calls it "la extinta ADS", which points that way.
- Adding a data ingest script triggers the README docs-sync coupling; the registry's script, `scripts/ingest_solid_waste_registry.py`, is documented in the README's real-data section.

## Open items

1. Hub confirmation of the Precedence rule (a hub-side ADR clarification would make it binding).
2. Whether hub ADR 0006 reaches `spiderweb-pr`'s `imagery/` package.
3. `config/federation_manifest.yaml` says it mirrors `AGUAYLUZ_PR_SKILL.md`, which is not in this repository; that mirror cannot be updated here.
4. `docs/adr/` already contains two `ADR-0003-*` files. Not renumbered here.
