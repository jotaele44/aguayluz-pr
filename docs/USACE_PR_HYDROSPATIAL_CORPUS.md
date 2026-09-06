# USACE Puerto Rico Hydospatial Corpus v1

## Certification scope

This harvester targets a **bounded declared public-source universe**, not "100% of the Internet". The corpus is certifiable only when every declared source adapter is executed or explicitly dispositioned, every candidate manifestation is classified, report-family expansion closes, and arithmetic closes with zero unresolved residue inside the claim.

## Identity layers

Never collapse these identities:

1. **BYTE** — SHA-256 of retrieved bytes.
2. **SOURCE_MANIFESTATION** — one URL/repository occurrence at one retrieval time.
3. **LOGICAL_DOCUMENT** — one edition/report/appendix, which may have multiple source manifestations.
4. **PROJECT** — USACE project/study identity.
5. **WATERBODY** — canonical hydrographic entity or unresolved candidate.

`NAME_ONLY`, normalized names, counts, proximity and source absence are discovery evidence only.

## Source architecture

The initial declared universe includes Jacksonville District Environmental Documents, USACE Digital Library global and Project Management Reports searches, Jacksonville Regulatory public notices, Congressional fact sheets, Civil Works project pages, IWR Project Assistance Library, ERDC library/Knowledge Core and HQ publications. The terrestrial waterbody discovery universe is USGS NHDPlus HR for Puerto Rico with independent Puerto Rico GIS/SIGE crosschecks; marine project entities are retained separately until independently bound.

## Culebrinas positive regression

The uploaded `RioCulebrinasDPR_B_Geotec_jun2004.pdf` is the initial positive fixture. It is a Final Detailed Project Report/EA Appendix B geotechnical manifestation. The source states that 15 design core borings were performed in June 1998, with one additional borrow-site boring and design-hole depths of 15–49.5 ft. The uploaded bytes also contain an Appendix C heading near the end, so filename or outer-document labeling cannot prove a pure single-appendix logical identity.

The 2004 family discovered from the Jacksonville Environmental Documents index comprises Main Text, EA, Appendix A Hydrology & Hydraulics, Appendix B Geotechnical, Appendix C Design & Cost, Appendix D Real Estate and Appendix E Economics, plus a later Coastal Zone consistency manifestation.

## Restartability

Each raw download is written atomically and receives a sidecar receipt with URL, retrieval UTC, HTTP status, content type, byte count, SHA-256, redirect target and local path. Existing paths with different bytes are retained under a hash-suffixed name rather than overwritten.

## Required completion invariant

`SOURCE_TOTAL = RETRIEVED + EXCLUDED + UNAVAILABLE + UNRESOLVED`

`USACE_PR_HYDROSPATIAL_CORPUS_CERTIFIED` requires `UNRESOLVED = 0` within the frozen declared source universe and explicit source-family completion receipts.
