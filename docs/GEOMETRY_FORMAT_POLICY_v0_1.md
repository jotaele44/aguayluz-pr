# Geometry Format Policy v0.1

## Binding rules

1. Original source bytes remain immutable and independently hashed.
2. Canonical geometry remains in a full-fidelity representation (GeoPackage, PostGIS, GeoParquet, WKB/EWKB + explicit CRS/dimension metadata).
3. GeoJSON is an interchange representation, not byte identity.
4. TWKB is always a derived, noncanonical encoding.
5. TWKB admission requires a frozen source, known CRS and units, explicit precision, explicit XY/XYZ/XYM/XYZM dimension, round-trip conservation, application tolerance, and an independently retained canonical copy.
6. A validity-state change or vertex-count change during quantization is a hard failure even if the decoded geometry is valid.
7. Representative points/centroids are derived locators and must never replace polygon/line source geometry identity.

## AguaYLuz integration

The local-hydro importer may continue deriving representative lat/lon values for utility-asset rows, but that locator is not the canonical geometry. For any feature-bearing source, preserve or reference separately:

- source geometry type
- source CRS
- source byte hash
- canonical geometry manifestation/hash when generated
- derivation label for representative point/centroid

TWKB may be introduced only behind `geometry_format_policy.py::assess_twkb_admission` and only as an optional compact cache/transport derivative. The gate is intentionally outside the GUI-parity production discovery roots because it is a non-user-facing certification/policy control, not a new GUI capability.

## Hard negatives

- Missing CRS -> BLOCKED
- Implicit TWKB precision -> BLOCKED
- XYZ -> XY without explicit authorization -> FAIL
- validity state changed -> FAIL
- vertex count changed -> FAIL
- round-trip error > declared tolerance -> FAIL
- TWKB used as sole geometry of record -> FAIL
