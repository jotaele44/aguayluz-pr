# Río Culebrinas frontier integration

This directory is the AguaYLuz producer-side integration of the bounded Culebrinas scientific-frontier package.

## States
- Frontier design/evidence architecture: `PASS / CERTIFIED_DESIGN`
- SIGE service binding: `PASS`
- Exact SIGE aquifer feature/GlobalID: `BLOCKED_FEATURE_EXTRACTION`
- GeoPackage geometry: `NONCANONICAL_FIELD_SYSTEM`
- New experimental observations: `0`
- `KVI_MEASURED`: `BLOCKED_NO_FIELD_DATA`
- H1-H5: `OPEN`

The GeoPackage is retained as a field/evidence system only. It MUST NOT be treated as the authoritative Río Culebrinas aquifer polygon until the exact SIGE feature is extracted and bound through its GlobalID.

TheHub receives only the registry/control-plane manifestation; AguaYLuz remains the producer for water/hydrogeology evidence.
