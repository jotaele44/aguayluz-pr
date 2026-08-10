# Patillas synchronized data admission and stage-storage model v0.3

## Purpose

This design-only extension defines the minimum evidence-complete path from the frozen Patillas-Guayama pilot to one real volumetric balance window. It does not activate provider polling, runtime persistence, APIs, GUI components, exports, alerts, notifications, scheduling, migration, or deprecation.

## Authoritative stage-storage source

The source authority is the U.S. Geological Survey 2019 Lago Patillas bathymetric survey:

- Scientific Investigations Map 3471, DOI `10.3133/sim3471`.
- Companion data release, DOI `10.5066/P9Y2SCY1`.
- Datum: Puerto Rico Vertical Datum of 2002 (`PRVD02`).
- Published relation: stage-volume table at 1.0-meter intervals derived from the 2019 terrain model.
- Published anchor: 12.96 million cubic meters at 67.55 meters above PRVD02.

The v0.3 repository package freezes source identity, datum, validity, interval, and the published spillway-capacity anchor. It deliberately does **not** invent the remaining table. Real stage-to-storage conversion remains blocked until the complete table bytes are acquired, hashed, reviewed, and represented as ordered published points.

Legacy mean-sea-level elevations must not be mixed with PRVD02 values. The 2019 PRVD02 datum supersedes the older datum for this relation.

## Admission contract

A real window requires one exact common interval and every required observation:

1. upstream inflow rate;
2. reservoir stage at the window start;
3. reservoir stage at the window end;
4. gate or canal release rate;
5. direct Guayama treatment withdrawal rate;
6. downstream flow rate;
7. area-weighted precipitation volume;
8. evaporation volume;
9. documented reservoir operational-loss volume;
10. documented canal operational-loss volume.

Every real observation must be T1, nonprovisional, the accepted current revision, SHA-256 bound, associated with the exact topology state, and produced by a sensor or process with verified calibration state. Rate and interval-volume observations must cover the same interval. Stage observations may differ from the boundary timestamp by no more than 60 minutes.

The canonical balance unit is cubic meters. Accepted rates are cubic meters per second and cubic feet per second; conversions emit deterministic receipts. Unsupported units fail closed.

## Stage-storage transform

The transform is piecewise linear only between adjacent published points. It records the model hash, input datum, source hash, bracketing points, interpolation fraction, output, numerical uncertainty, and whether interpolation occurred.

Extrapolation is prohibited. A stage below the first point, above the final point, in a different datum, or evaluated against an incomplete model raises an explicit error and produces no storage estimate.

## Rate-volume transform

A constant interval rate is converted by:

`volume_m3 = rate * unit_conversion_to_m3_per_second * duration_seconds`

The same interval multiplier is applied to absolute rate uncertainty. Every result includes a replayable receipt and source hash.

## Nested synthetic proof

The complete synthetic fixture closes two boundaries independently:

- Reservoir: upstream inflow + direct precipitation - release - evaporation - reservoir operational loss - storage change.
- Canal/treatment: canal release - direct treatment withdrawal - downstream flow - canal operational loss.

Both residuals are zero. The synthetic curve and observations are T4 regression artifacts and do not describe actual Lago Patillas, Guayama Filtration Plant, PREPA, AAA, or any downstream intake.

## Real-window decision

No real balance is executed in v0.3. The blocking conditions include the unmaterialized full stage-volume table, absent synchronized treatment withdrawal and downstream terminal flow, absent full-window gate release, and absent precipitation, evaporation, and documented-loss volumes for one common interval.

A residual, once computable, remains an accounting discrepancy. It is not evidence by itself of leakage, theft, fraud, illegal diversion, unauthorized activity, or an exact failure location.

## Rollback and promotion

Rollback deletes only the additive v0.3 research, fixture, test, receipt, matrix, and documentation paths. Runtime packages and interfaces remain untouched.

Any runtime or interface promotion requires:

- complete authoritative table materialization;
- at least one fully admitted real T1 window;
- overlap re-adjudication after sibling PR head movement or merge;
- exact-head repository CI;
- a separate approved promotion ballot.
