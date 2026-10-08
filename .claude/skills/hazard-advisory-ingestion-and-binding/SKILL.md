# Hazard Advisory Ingestion and Binding Skill

## Purpose
Build restartable, provenance-preserving ingestion pipelines for Puerto Rico food, agricultural, animal-health, infectious-disease, wastewater, water-health, and environmental-health advisories without conflating source taxonomy, geographic coincidence, identity, exposure, association, or causation.

## Required contract
1. Freeze source URL/service/layer/query, retrieval UTC, refresh/update metadata, raw bytes where retrievable, SHA-256, schema signature, and source record count before normalization.
2. Preserve RAW, NORMALIZED, and CANONICAL values separately. Never use normalization as sole identity proof.
3. Model EVENT, OBSERVATION, ADVISORY, ACTION, MANIFESTATION, and RELATIONSHIP separately.
4. Preserve source revisions. A later manifestation may supersede an earlier record but must not overwrite its bytes or temporal state.
5. Permit 1:1, 1:N, N:1, N:N, 0:1, and UNRESOLVED relationships. Do not synthesize one row by aggregating fields from multiple candidates.
6. For human disease records, preserve suspected/probable/confirmed class, case-definition version, provisional/final/revised state, reporting geography, observation period, and report date.
7. For recalls, preserve recall/enforcement identifiers, product/lot/UPC/establishment/distribution semantics, and explicit Puerto Rico relevance state.
8. For spatial bindings, retain source geometry and derived geometry separately; record method, precision, CRS when available, topology state, and evidence class.
9. Nearest-neighbor, fuzzy match, search results, bounding boxes, buffers, and proximity are discovery unless independently bound.
10. Never promote SAME_LOCATION, SAME_WATERSHED, SAME_SEWERSHED, TEMPORALLY_OVERLAPS, or proximity into confirmed exposure or causation.

## Evidence order
stable ID → authoritative binding → certified geometry → point-in-polygon + independent alias/ID → point-in-polygon → authoritative alias + spatial/temporal support → historical continuity + corroboration → proximity → unresolved.

Hard evidence overrides heuristics. Tied top evidence remains REVIEW/UNRESOLVED.

## Causality firewall
`CAUSALLY_CONFIRMED` requires authoritative evidence. `STATISTICAL_ASSOCIATION` requires a documented method and sample size and must retain effect-size/confidence information when available. Proximity-only evidence must fail validation for causal or epidemiological predicates.

## Arithmetic/invariants
For every source manifestation assert:

`SOURCE = RETAINED + EXCLUDED + UNRESOLVED`

Also assert stable-ID uniqueness where expected, required fields, allowed enums, temporal ordering, no silent null-to-island-wide geography promotion, join cardinality, no unintended duplication/multiplication, no dangling relationships, and no missing source manifestations.

Any unexplained mismatch fails closed.

## Certification states
PASS | FAIL | OPEN | BLOCKED | PROVISIONAL | AUDIT_ONLY | NONCANONICAL | CANDIDATE_NOT_IDENTITY | UNRESOLVED | SUPERSEDED

Script success is not certification. Certification requires bounded source scope, frozen inputs, explicit exclusions, full classification, arithmetic closure, identity/cardinality adjudication, temporal and spatial validation, provenance hashes, passed positive/negative regressions, and zero material unresolved residue inside the claim.

## AguaYLuz integration rule
AguaYLuz is a consumer of the canonical hazard plane, not the substantive authority for epidemiology, food safety, agriculture, or animal health. The environmental-exposure GUI may render the hazard plane, but source authority and causal semantics remain external and provenance-bound.

## Verified bounded periodic-archive pattern

When an authoritative advisory source is published as a reverse-chronological paginated archive rather than a structured API:

1. Derive chronology from authoritative notice metadata, not URL numbering, search ranking, or archive-card text.
2. For a bounded publication-year certification, traverse sequentially and fetch every candidate notice on each visited page.
3. Verify notice publication dates are monotonically non-increasing across the traversed page boundary.
4. Stop only after one complete out-of-range overlap page has been frozen and every notice on that page has a resolved publication date. Any unresolved boundary date or ordering violation fails closed and requires continued traversal or adjudication.
5. Freeze both archive-index pages and notice pages with manifestation IDs, byte hashes, and raw-file mappings.
6. Threshold observations and advisories are independent semantics. A source may issue an advisory for a reason other than a numeric threshold exceedance; never infer one from the other.
7. Preserve program-wide all-clear notices as source states without fabricating station-level negative observations.
8. Certify only the bounded publication denominator demonstrated by the receipt. Historical backfill and broader source-universe completeness remain separate OPEN vectors unless independently exhausted.

