# AguaYLuz PFAS Certification Checkpoint — 2026-09-03

## Baseline
- Preserved filesystem tree: `639ec827ba48f79edc40c29e8a6b938cf3e5833e`.
- The tree is represented by commit `91ab202387240ee3509793c1ff73d5b481f50125`.
- Working branch: `pfas-certification-20260903`.
- No passed pre-existing AguaYLuz artifact was deleted or rewritten.

## Scope
Puerto Rico PFAS evidence plane spanning authoritative drinking-water occurrence data, environmental PFAS sites, treatment-program evidence, federal regulatory chronology, and safeguarded entity/spatial/causal bindings into the existing AguaYLuz environmental exposure architecture.

## Implemented
- Fail-closed PFAS evidence primitives in `src/aguayluz/pfas.py`.
- Canonical initial registry for PFOA, PFOS, PFHxS, PFNA, HFPO-DA and PFBS.
- Strict non-detect semantics; numeric values cannot be synthesized for `<MRL` records.
- Unit normalization for ng/L-ppt and ug/L-ppb.
- Identity cardinalities: 1:1, 1:N, N:1, N:N, 0:1, UNRESOLVED.
- Spatial terminal states aligned to federation requirements.
- Attribution gate prohibiting discovery/proximity/name-only evidence from promoting causation.
- Temporal regulatory model preserving in-force rules while separately recording proposed rescission/extension actions.
- Rule comparison returns reference context only and can never turn a single UCMR occurrence value into a compliance finding.
- Authoritative source-manifestation ledger.
- Puerto Rico site-evidence ledger with Fort Allen, Vieques, Gurabo PFAS pilot, and islandwide wells pilot semantics.
- Reusable Environmental Contaminant Certification skill.
- Positive/negative PFAS regression tests.

## Authoritative evidence findings
### Fort Allen
Final National Guard/USACE site inspection evidence supports measured groundwater PFAS at AOI 1. The report states all five relevant compounds were detected in groundwater; PFOS, PFOA, PFNA and PFHxS exceeded the report's screening levels, with reported maxima of 540, 240, 120 and 190 ng/L respectively. Further remedial investigation was recommended. This does **not** automatically establish a PRASA-system impact or off-site human exposure.

### Vieques
NAVFAC identifies 13 possible AFFF/PFAS source-release areas and reports PFAS sampling. The Navy also states Vieques groundwater is not used as drinking water and the island receives drinking water by pipeline from mainland Puerto Rico. Accordingly, AguaYLuz records the potential-release evidence but explicitly excludes a direct local-groundwater drinking-water pathway unless later authoritative evidence changes that conclusion.

### Puerto Rico drinking-water program
EPA UCMR 5 is the canonical occurrence dataset and was finalized in August 2026. PRASA's FY2024 report documents UCMR5 sampling implementation and PFAS-rule implementation activity. Puerto Rico Department of Health DWSRF records identify a $7.5M Gurabo WTP PFAS pilot and a $7M islandwide wells PFAS pilot. Funding/project evidence is not interpreted as proof of a contaminator or release source.

## Regulatory state as of 2026-09-03
- PFOA MCL: 4 ng/L, current in-force 2024 rule.
- PFOS MCL: 4 ng/L, current in-force 2024 rule.
- PFHxS/PFNA/HFPO-DA and Hazard Index provisions remain part of the published 2024 rule while EPA's May 18, 2026 rescission action remains proposed.
- EPA's May 18, 2026 PFOA/PFOS compliance-extension action remains proposed; the model does not preemptively replace the current rule chronology with 2031.

## Certification residue
`AGUAYLUZ PFAS CERTIFIED` is **not** issued.

Material open items:
1. The final EPA UCMR5 Puerto Rico state ZIP must be frozen as raw bytes, SHA256 hashed, schema-inspected, and ingested whole-row. The execution environment exposed the authoritative ZIP URL but could not retrieve the binary payload; no secondary reconstruction is substituted for it.
2. Every mutable/public web manifestation in `data/pfas_source_manifestations.jsonl` still has `byte_sha256=null`; therefore byte-level provenance is OPEN.
3. The complete National Guard/DoD/Navy Puerto Rico PFAS document denominator has not yet been downloaded and member-hashed. The authoritative Puerto Rico index is frozen as a source manifestation, but every listed report has not been byte-certified.
4. Exact UCMR public-water-system/sample-point observations and their stable IDs are therefore not yet integrated into the environmental observation graph.
5. Water-system-to-treatment-plant/source-water geometry bindings for all PFAS-positive UCMR manifestations remain unadjudicated.
6. Corporate/manufacturer/source attribution is intentionally empty pending independent authoritative evidence; no AFFF site is bound to a manufacturer by product-category inference.
7. Litigation coverage is not certified exhaustive. Allegation-state support exists in the evidence grammar, but no case is promoted without case-record acquisition.
8. CI must pass on the pull request before the implementation checkpoint can be marked regression-PASS.

## Current certification state
- Evidence architecture: PASS
- Identity safeguards: PASS
- Spatial/causal safeguards: PASS
- Temporal regulatory safeguards: PASS
- Authoritative-source discovery: PASS (bounded sources above)
- Raw-byte provenance: OPEN
- UCMR Puerto Rico whole-row ingestion: BLOCKED in current execution environment
- Complete Puerto Rico PFAS denominator: OPEN
- Application regression: OPEN pending CI
- Overall: **OPEN / NOT CERTIFIED**

The branch must remain fail-closed until every material open item is closed or explicitly bounded outside a narrower certification claim.
