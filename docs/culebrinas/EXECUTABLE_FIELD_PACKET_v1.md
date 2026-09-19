# Río Culebrinas Scientific Frontier — Executable Field Packet v1

## Scope
This packet converts the certified design into an executable, fail-closed campaign. It does **not** authorize site entry, drilling, electrode installation, water entry, boating, sampling, or work on private property. Each deployment requires the land manager/owner authorization and a site-specific safety plan.

## Pre-deployment gates
1. Exact authoritative SIGE aquifer feature + GlobalID frozen.
2. Station candidates intersect the canonical feature or are independently justified outside it; no proximity-only binding.
3. Access permissions and right-of-way constraints closed.
4. Survey control established for every new station.
5. Instrument calibration records present and hashed.
6. Chain-of-custody forms prepared for every laboratory sample.
7. All raw files and forms assigned deterministic IDs before collection.

If any gate is open: **do not collect data; issue explicit gap receipt.**

## Campaign 1 — Baseline heads / EC / temperature
Install or instrument nested monitoring points only where authorized. Collect continuous head, specific conductance and temperature. Preserve screen interval, casing/screen construction, surveyed elevation, datum and CRS. Minimum design target: dry-season and wet-season coverage; no hypothesis adjudication from a single visit.

## Campaign 2 — Río Culebrinas gain/loss
Conduct repeated synoptic differential-discharge runs under stable baseflow. At each reach preserve upstream/downstream discharge, tributary inputs, withdrawals/returns, measurement uncertainty and synchronization time. Final reach state is `GAINING | LOSING | NEUTRAL_WITHIN_ERROR | UNRESOLVED`; arithmetic must close within stated error.

## Campaign 3 — Karst→valley / paleochannel hydrogeophysics
Acquire ERT and/or TEM on canonical transects after utility clearance and access approval. Preserve raw instrument coordinates, acquisition geometry, electrode/loop spacing, inversion parameters and model misfit. Geophysical anomalies remain `CANDIDATE_NOT_IDENTITY` until independently ground-truthed by boring/log or hydraulic evidence.

## Campaign 4 — H3 structural test
Ingest the UPRM 2026 PR-418 seismic interpretation as an independent manifestation. Compare candidate structural geometry against head, chemistry and hydraulic responses without using proximity alone to establish causal identity. H3 remains `UNRESOLVED` if the seismic interpretation is inconclusive.

## Campaign 5 — Fresh/salt interface
Use nested EC profiles plus an independent electromagnetic method where practical. Record tidal stage/time for coastal observations. Final states are `FRESH | MIXED | SALINE | TEMPORALLY_VARIABLE | UNRESOLVED`; preserve observed profiles separately from interpolated surfaces.

## Campaign 6 — Coastal SGD
Only after a seaward hydraulic gradient is independently supported, conduct repeated coastal temperature/salinity reconnaissance and at least one independent tracer/flux method (for example radon/radium or seepage measurement). A thermal or salinity anomaly alone is discovery evidence, not SGD identity.

## QA/QC minimums
- stable IDs for stations, instruments, samples, calibration records and raw files;
- UTC timestamps with timezone;
- field duplicates where analytically appropriate;
- laboratory blanks/standards according to method;
- calibration valid at observation time;
- complete chain of custody;
- raw-byte SHA256 before transformation;
- no silent unit conversion;
- CRS/datum stored explicitly;
- NULL remains NULL; no zero-filling;
- rejected records preserved in rejection ledger.

## H1–H5 adjudication
Each hypothesis must end in `SUPPORTED | FALSIFIED | UNRESOLVED`. No hypothesis may be marked supported solely because a model fits calibration data. Positive evidence and falsifier tests are both required.

## KVI_MEASURED gate
`KVI_MEASURED` is prohibited until all ten readiness gates in `config/culebrinas_field_operator_packet.v1.json` are true and the method passes a withheld validation set. `KVI_READINESS` and `KVI_MEASURED` are separate products.

## Certification
A complete packet may become a **certification candidate** only after canonical geometry, field QA/QC, hypothesis adjudication, measured KVI, withheld validation, row/cardinality invariants and zero material unresolved residue all pass. Production promotion remains a separate explicit action.
