# Ionosphere RC3 — cross-repository frozen transport and scope closure

Overall state: PROVISIONAL. No production activation or skill promotion.
Preserve RC0, RC1, RC2 and all original capture bytes; no mutable TEC source was
redownloaded for this tranche. Producer PR: https://github.com/jotaele44/skywatcher-pr/pull/354
Consumer PR: https://github.com/jotaele44/aguayluz-pr/pull/367

## Producer-consumer binding

PITIRRE repository ID 1261399537, candidate commit
5794c5cb7f97c37de8f210570a657d8bfb690aa5. Its 11 observed CI workflows passed,
including core CI, GUI parity, compatibility, runtime contracts and security.
New observation v2 is additive; v1 schemas/adapters are unchanged. Internal
SPACE.SPACE_WEATHER glotec_model envelopes retain complete source features and
prohibit operational use. Source indices bind immutable rows, not physical entities.

Exact export SHA256: 4bcbc60a48075456b022f085c6972b54e145fe987e46a2b89c0b23eaa60d7e6d.
The exact persisted bytes are committed to both repositories. Aguayluz validates
schema and package hashes, producer ID, source/retained/excluded counts, every
whole feature, source index, source epoch, coordinate role, source manifestation
and use policy. API -> GUI -> source-lineage display and 78-row reference inspection
are wired under the existing OFF preview flags. The displayed values are projected
from the validated persisted producer envelopes; the original raw archive is an
independent verification input, not a parallel numeric display source. Read-only replay is idempotent;
no operational database is written or joined. Six retained + 5,178 excluded = 5,184.
The manifest pins producer code/schema Git blobs and the published candidate SHA.

## Reference coverage

All 78 valid geometries in the existing frozen generalized Census-derived
municipio reference are FULLY_WITHIN the actual source grid-node coordinate envelope
and the context bbox. Stable raw GEOIDs are unique; every source row is retained.
Source CRS: CRS84 (longitude, latitude); no Z/M or reprojection loss. No geometry
repair, station identification, area interpolation or municipality measurement
claim is made. This is bounded reference-envelope coverage, not local observation
support or legal-boundary/EEZ completeness. Full deterministic report is
 data-sources/ionosphere/reference_coverage.json. The CI topology gate recomputes
it and exercises FULLY_WITHIN/PARTIAL/TOUCH_ONLY/OUTSIDE/NULL_EMPTY/UNRESOLVED cases.

## EPA drift adjudication and recovery

Recovered the previously PASS artifact 12508351665 from run 39968848835; artifact
SHA256 312c47f198ed7b749a7acb50058878f06763ed680d0fb6e507d85f59fc86b797.
Both historical and new national archives are preserved in that artifact. It is
also checkpointed durably for the owner; no mutable redownload is required to
reproduce this gate. CI downloads the exact fixed artifact and checks its digest.
The GitHub copy has retention through 2027-01-21; future loss fails closed and must
be restored from the preserved identical bundle, not a newly downloaded source.

National archive classification: DISTINCT_PAYLOADS. File-member intersection=3,
A_ONLY=3, B_ONLY=3, UNION=9, SYMMETRIC_DIFFERENCE=6. Payload multisets differ. Full
PATH + SIZE + SHA256 inventories are retained in pfas_frozen_scope_receipt.json.
This is not pure recompression and no national byte/logical equivalence is claimed.

Independently re-derived the PR subset from both original frozen national members,
using inspected cp1252 literal-tab field semantics and exact 24-field positional
schemas. Source text contains literal quotes; a strict CSV interpretation fails.
No string normalization, uppercasing, missing-field coercion, or row synthesis.
All source row widths, PR ID/State consistency and canonical TSV bindings pass.

| Source member | Source rows | PR retained | Excluded |
|---|---:|---:|---:|
| Historical | 1,191,356 | 21,771 | 1,169,585 |
| Observed | 1,191,331 | 21,771 | 1,169,560 |

PR row-multiset INTERSECTION=21,771; A_ONLY=0; B_ONLY=0; UNION=21,771;
SYMMETRIC_DIFFERENCE=0. Raw PWSID sets also agree (99/99), but count equality is
not used as identity proof. The exact canonical PR TSV SHA256
ac40d8d67f7343832e0b11d78c892e3a6cdd44fe4d0b0892407347d4400b80c5 is preserved.
The workflow now verifies PASS_FROZEN_PR_SCOPE_NATIONAL_DISTINCT without rewriting
canonical data or pretending to monitor live EPA updates. National differences
remain explicit. Occurrence records are not compliance determinations.

## ROTI acquisition and unresolved contract

A current public DLR/IMPC processed ROTI capture was acquired and retained privately:
source interval 2026-10-23 17:19–17:20 UTC; raw SHA256
1bf8fe2803938cd2d815ab6d82788536c146eb183b10cd84ac5f74bf37695bc3.
There are 4,031 source-reported receiver/satellite link features; 51 fall in the
broad reported-coordinate discovery window. Full raw candidate sets are preserved.
Those point coordinates must not be equated with physical receiver locations.
EarthScope authentication is no longer a blocker for processed ROTI acquisition.

Metadata declares a 60-second calculation window and 1 Hz inputs. The same product
family's separate 17:45 UTC image labels units TECU/min; the raw JSON has no explicit
ROTI units field. Source metadata mixes ECEF with EPSG:4326/degrees; the 180-by-90
matrix differs from the web description's axis example. A full-grid candidate
matrix/point-bin diagnostic agrees within 0.0011 for 988 of 1,008 occupied bins;
20 bins remain unexplained. No inferred axis, zero semantics, global completeness,
canonical geography or operational metric is promoted from that diagnostic.

DLR scientific-use and redistribution terms apply. Raw DLR data are not in the
public repository or shipped application. Product metadata/audit findings and
credit are in data-sources/ionosphere/roti_provider_audit.json. Licensed numeric
rendering and provider-contract adjudication remain OPEN; no external contact
or license acceptance on behalf of third parties was performed.

## Packaging, verification and gates

The desktop spec now includes only the small ionosphere source directory. New
readers use PyInstaller's bundle root when present. A subprocess fixture asserts
that the simulated frozen bundle uses its own source archive and validated
producer/reference files, rather than silently falling back to the checkout.
Actual installed-device, upgrade and live-refresh proofs remain separate.

Local: producer/legacy 13 tests PASS; consumer/source-scope regression suite 28 tests
and 25 parameter subtests PASS; ruff, reference topology and parity gates PASS.
The independent EPA source verifier also re-derived both national PR subsets with
1,191,356 / 1,191,331 source rows and no PR ID/State contradictions.
Exact new consumer HEAD requires CI; inherited RC2 results are not RC3 certification.

ION-01 PASS. ION-02/08 bounded software acceptance pending new consumer CI.
ION-03 exact TEC snapshot acquisition PASS. ION-04 frozen reference-envelope
coverage PASS only within its defined scope. ION-05 acquisition PASS, interpretation
and redistribution UNRESOLVED. ION-06/07 persisted frozen transport passes locally
and producer CI; final consumer CI pending. ION-09/10 complete release, operational
refresh, deployment and reusable-skill promotion remain BLOCKED.
Plan score 96/100; hardening strategy 98/100 (design judgments, not completion scores).
