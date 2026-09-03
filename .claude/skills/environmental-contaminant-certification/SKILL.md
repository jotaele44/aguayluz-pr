# Environmental Contaminant Certification Skill

## Purpose
Build a fail-closed contaminant evidence plane for AguaYLuz-PR without converting discovery signals, allegations, proximity, or source absence into identity or causation.

## Required sequence
1. Freeze source manifestation metadata before interpretation: authority, title, URL/service/layer/query, retrieval UTC, publication/refresh date, byte SHA256 when retrievable, schema and row count.
2. Preserve RAW, NORMALIZED, and CANONICAL values separately. Normalization is never identity proof.
3. Build analyte registry with stable chemical identifiers (prefer CASRN plus authoritative analyte code).
4. Ingest analytical observations whole-row. Preserve non-detects as non-detects; never synthesize numeric zero or MRL values.
5. Separate site/release evidence from drinking-water-system identity and exposure pathways.
6. Retain all candidate bindings and classify identity cardinality as 1:1, 1:N, N:1, N:N, 0:1, or UNRESOLVED.
7. Spatial discovery (search/bbox/buffer/nearest) cannot promote causal state. Final spatial states are FULLY_WITHIN, PARTIAL, TOUCH_ONLY, OUTSIDE, NULL_EMPTY, or UNRESOLVED.
8. Preserve regulatory rules temporally. A proposed rescission or extension must not overwrite the currently in-force rule until final action is authoritative.
9. Treat litigation allegations as ALLEGED unless independently corroborated. Defendant identity is not contaminator identity.
10. Run positive and negative regression gates for nulls, ties, duplicates, M:N joins, unit conversion, non-detect semantics, temporal rule selection, and proximity-only attribution.
11. Require arithmetic closure and zero material unresolved residue for CERTIFIED. Script success alone is not certification.

## PFAS implementation rules
- Canonical initial analytes: PFOA, PFOS, PFHxS, PFNA, HFPO-DA, PFBS.
- UCMR 5 is an occurrence dataset. A single UCMR value may be compared to an MCL as reference context but is not itself a compliance determination.
- PFOA/PFOS 4 ng/L MCLs remain the current rule baseline unless a later final federal action supersedes them.
- Proposed 2026 rescission of PFHxS/PFNA/HFPO-DA/Hazard Index and proposed PFOA/PFOS compliance extension must remain separate temporal regulatory manifestations until finalized.
- DoD/Navy AFFF use or a potential release area does not establish a manufacturer, off-site plume, public-water-system impact, or human exposure without independent evidence.

## Certification output
Return PASS only when: source denominator is defined, mutable inputs are frozen and hashed, schema/row counts close, identifiers are validated, observations and binding cardinalities close arithmetically, spatial/temporal/legal contradictions are adjudicated, tests pass, and unresolved material residue equals zero. Otherwise return OPEN/BLOCKED with exact residue and preserve every passed artifact.
