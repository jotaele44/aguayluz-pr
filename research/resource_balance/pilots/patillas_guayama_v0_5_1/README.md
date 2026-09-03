# Patillas–Guayama v0.5.1 stage-area and hourly QPE

Design-only extension of the v0.5 T1 coverage package.

This package binds the certified 2019 USGS Patillas terrain evidence to a PRVD02 stage–area relation and freezes one NOAA/NWS Puerto Rico Stage IV one-hour GeoTIFF for deterministic precipitation-volume replay.

Key constraints:

- stage area is derived only at the published stage knots from the terrain-generated USGS stage–storage relation, with the 67.55 m PRVD02 knot cross-bound to the authoritative 2019 shoreline polygon;
- the published 44.55–45.55 m zero-storage plateau remains non-interpolable;
- no stage extrapolation is allowed;
- the frozen NOAA observation band is in inches and HRAP cell polygons must be transformed to EPSG:6566 before physical-area measurement;
- any intersecting no-data cell rejects the transform;
- scalar stage area is not enough to spatially weight multiple Stage IV cells at lower stages: a stage-specific water-surface geometry binding is required;
- the public-byte replay at 67.55 m computes only the precipitation subcomponent and remains non-admitted because a numeric QPE uncertainty is not supplied by the frozen sample itself;
- no complete water balance, runtime/API/GUI/export/alert/notification/scheduler/control action is activated.
