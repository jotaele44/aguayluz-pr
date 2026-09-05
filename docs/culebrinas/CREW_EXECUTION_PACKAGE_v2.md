# Río Culebrinas Frontier — Crew Execution Package v2

## Certification boundary
This document is an executable acquisition specification, not an authorization to enter land, drill, place electrodes, enter water, operate a boat, or collect samples. `TEMPLATE_NOT_OBSERVATION` is the default state until every predeployment gate is independently closed.

## Stop-work rule
If canonical aquifer feature + GlobalID, written access authorization, site safety plan, survey control, utility clearance where applicable, current calibration, chain-of-custody readiness, deterministic IDs, or raw-byte hashing is missing: **STOP COLLECTION and issue a gap receipt.**

## Roles
- Field lead: closes access/safety gates and freezes daily station plan.
- Survey lead: establishes station coordinates, CRS, datum and elevations.
- Instrument lead: owns calibration and raw-file manifests.
- Sample custodian: owns sample IDs, preservation and chain of custody.
- Data custodian: hashes raw bytes before transformation and ingests only v3-valid observations.
- Scientific adjudicator: is separate from raw-data acquisition where practical and cannot change withheld IDs after model fitting begins.

## Daily launch sequence
1. Verify frozen canonical `GlobalID` and current geometry hash.
2. Verify authorization IDs for every station/reach/transect.
3. Verify site-specific hazard and communication plan.
4. Verify survey control and instrument clocks in UTC.
5. Verify calibration validity and calibration IDs.
6. Preassign station/sample/observation/raw-file IDs.
7. Freeze calibration/withheld partition before model fitting.
8. Create empty rejection and gap ledgers.
9. Begin collection only after all checks PASS.

## Campaign H1 — karst → valley transfer
Collect nested groundwater head, specific conductance, temperature, major ions, δ18O/δ2H and independent ERT/TEM coverage. Repeat across hydrologically contrasting periods. A correlated gradient is not sufficient by itself; competing recharge/source explanations must be tested.

## Campaign H2 — paleochannel control
Acquire ERT/TEM, independently ground-truth anomalies with boring/log or hydraulic evidence, and perform slug/pumping response tests where authorized. Geophysical anomaly alone remains `CANDIDATE_NOT_IDENTITY` and is barred from experimental identity promotion.

## Campaign H3 — structural control
Recover the final UPRM PR-418 seismic interpretation before adjudication. Cross the candidate structure with head, chemistry and hydraulic response observations. A spatial coincidence without response contrast is insufficient.

## Campaign H4 — fresh/salt interface
Acquire repeated nested EC profiles plus an independent EM method with synchronized tidal context. Preserve raw vertical profiles; interpolation is a separate model manifestation.

## Campaign H5 — coastal SGD
Require independently supported seaward hydraulic gradient first. Then acquire repeated coastal temperature/salinity and at least one independent tracer/flux method, with two independent methods overall. A thermal/salinity anomaly alone is discovery evidence only.

## Río Culebrinas gain/loss
Repeat synchronized differential-discharge runs under stable baseflow. Preserve upstream/downstream Q, tributaries, withdrawals, returns and uncertainty. Reach result: `GAINING | LOSING | NEUTRAL_WITHIN_ERROR | UNRESOLVED`. Arithmetic must close within stated uncertainty.

## Raw evidence and QA/QC
- Raw bytes are immutable and SHA256-hashed before transformation.
- UTC timestamps are mandatory.
- Station and sample identities are stable and unique.
- CRS and datum are explicit; no silent transformation.
- Calibration must be valid at observation time.
- Laboratory samples carry chain-of-custody IDs.
- NULL remains NULL; no zero filling.
- Failed/rejected records remain in the rejection ledger.
- Proposed, inferred and modelled rows never enter the experimental observation store.

## Withheld validation
Withheld observation IDs are frozen before model fitting. Calibration and withheld sets must be nonempty, disjoint and hash-manifested. The withheld result is evaluated only after the predictive model and thresholds are frozen. A failed withheld test blocks `KVI_MEASURED` promotion and final certification.

## H1–H5 evidence receipt
Every hypothesis requires positive-evidence IDs, falsifier-test IDs and independent-method identifiers. `SUPPORTED` requires positive evidence plus >=2 independent methods; `FALSIFIED` requires a triggered predeclared falsifier. `UNRESOLVED` is material residue and blocks final certification.

## KVI_MEASURED
Run only after the strict evidence receipt declares real authorized observations, canonical geometry, QA/QC closure, every KVI component measured, withheld validation PASS and zero material residue. Test fixtures can exercise arithmetic but are permanently marked `MEASURED_TEST_FIXTURE` and cannot become `KVI_MEASURED`.

## End-of-day close
1. Hash every raw file and manifest.
2. Reconcile expected = collected + rejected + explicitly missing.
3. Verify all observations reference known stations, authorizations and calibrations.
4. Verify sample rows reference chain of custody.
5. Validate NDJSON with `operators/validate_culebrinas_field_ingest_v3.py`.
6. Preserve rejection/gap ledgers.
7. Sign/freeze the daily packet; do not mutate raw evidence after freeze.

## Final promotion gates
Final `CULEBRINAS FRONTIER GEOMETRIC/EXPERIMENTAL CERTIFIED` is prohibited unless all are true: canonical SIGE geometry + GlobalID frozen; complete defined subsurface census closed; USACE boring geometry/CRS closed; UPRM interpretation recovered; field QA/QC closed; real observations present; KVI_MEASURED computed; sensitivity/uncertainty reported; H1–H5 adjudicated with no unresolved state; withheld validation PASS; row/join/hash/cardinality invariants PASS; producer/control-plane federation CI green and merged; zero material residue.
