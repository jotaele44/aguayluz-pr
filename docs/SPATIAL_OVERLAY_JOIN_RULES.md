# Spatial Overlay Join Rules

The Federation distinguishes **image-pixel context** from **world-space GIS**. The legacy
Puerto Rico saturated grid remains a shared pixel-context index, but it is not a geographic
index until an independently certified world binding exists.

## Pixel-context rules

1. `registry/spatial/pr_grid_full_cell_index_saturated.csv` is `PIXEL_CONTEXT_ONLY`.
2. Preserve `Cell_ID`, `Row_Index`, and `Column_Index` for observations that are already in
   the exact same evidenced pixel coordinate frame.
3. Do not assign a CRS, geographic bounds, affine transform, or source-raster identity to the
   pixel grid without a separately certified world-binding derivative.
4. `coordinate_to_cell_resolution_allowed: false` while the world binding is unresolved.
5. Municipality, barrio, watershed, utility, reservoir, hydrography, trajectory, or other
   world-space geometry MUST NOT be joined to `Cell_ID` through an inferred transform.
6. `Land_Pixel_Ratio` and `Classification` are pixel-context attributes only.

## World-space overlay rules

1. Cross-repository world-space overlays must use datasets with explicit source provenance,
   stable feature identifiers, and a certified CRS or a standards-defined GeoJSON CRS.
2. Preserve each producer's source identifier and geometry provenance in derived relations.
3. Record source file/path or URL, source hash when bytes are materialized, run timestamp,
   operation semantics, computation CRS, and numeric tolerances.
4. Treat boundary overlays as many-to-many unless the selected predicate and source ontology
   establish a stronger cardinality rule.
5. Provider choice (local GeoPandas, Apache Sedona, Wherobots, or another implementation) must
   not alter the canonical Federation schema or source authority.
6. Provider-specific job IDs, runtime names, cluster identifiers, and cost fields belong only
   in execution receipts, never canonical domain records.

## Current shadow reference

`config/spatial_compute_shadow_v0_2.json` defines the first provider-neutral world-space
reference overlay as the 78 Puerto Rico municipios against the 901 barrio polygons generated
from U.S. Census Bureau 2023 cartographic boundary sources. The legacy pixel grid is explicitly
excluded from this benchmark.
