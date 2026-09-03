# Lago Patillas stage–area and hourly precipitation transform v0.5.1

## Evidence basis

The source is USGS data release `10.5066/P9Y2SCY1` and report `10.3133/sim3471`. The previously certified source archive is retained at 27,171,688 bytes with SHA-256 `3beac301b1521a197837ebb49eff701e2774385cb34f220e3546c82c5d732ea7`. The terrain uses NAD83(2011) / Puerto Rico and Virgin Islands (EPSG:6566) horizontally and PRVD02 (EPSG:6641) vertically; the release describes a 1 m terrain product.

The merged repository contains only the physical FileGDB components needed for the published `Patillas2019_volume` table, so v0.5.1 recovered the complete previously certified workflow artifact rather than pretending those three files represented the terrain surface.

## Stage–area construction

The published 24-row stage–storage table is itself a terrain-derived USGS product. v0.5.1 applies a shape-preserving PCHIP to the valid non-plateau stage–storage sequence and evaluates its derivative at the published stage knots. No source stage rows are inserted.

The 44.55–45.55 m PRVD02 zero-storage plateau remains an explicit precision contradiction: area is unresolved there and interpolation across the interval is prohibited.

At 67.55 m PRVD02 the derivative gives 1,200,000 m² while the authoritative shoreline polygon measures 1,203,713.982 m². The 3,713.982 m² difference is 0.309%; the model therefore binds the top knot to the direct shoreline area and retains the derivative as a cross-check.

Published storage is rounded to 0.01 million m³. The per-knot `publication_precision_sensitivity_m2` field records sensitivity to ±0.005 million m³ storage rounding; it is not a claim of total physical area uncertainty. USGS terrain vertical-accuracy context is retained separately.

## Frozen NOAA Stage IV sample

A one-shot, read-only GitHub acquisition fetched `https://water.noaa.gov/resources/downloads/precip/stageIV/current/nws_precip_1hour_pr.tif`.

The exact TIFF is 5,882 bytes with SHA-256 `56aaa69d6d1e4ef33aac4e4c4c5ec4a2e24a7d2d9cd5f30b22805caa243d06f1`. NOAA tags report `data_time=20260808T00:00:00` and `creation_time=20260808T010324`.

The 205×205 raster uses NOAA HRAP polar stereographic coordinates. Band 1 is the observation band in inches. Physical reservoir intersection areas are measured only after each HRAP cell polygon is transformed into EPSG:6566.

## Public-byte replay

At the authoritative 67.55 m shoreline the reservoir intersects two observation cells. Their EPSG:6566 intersection areas sum to 1,203,713.982 m², matching the shoreline geometry. Using the frozen observation depths yields 439.207323 m³ of direct precipitation and an area-weighted depth of 0.000364877 m.

This is a deterministic precipitation-subcomponent replay, not a water balance. It remains **not admitted** because the frozen NOAA sample does not itself provide the numeric QPE uncertainty required by the v0.5 admission contract.

## Structural limitation

A scalar stage–area function cannot determine how a lower-stage reservoir polygon overlaps two or more Stage IV cells with different precipitation depths. Therefore arbitrary lower-stage QPE volume is fail-closed unless a stage-specific water-surface geometry is bound or a separately validated spatial-allocation model is approved.

No real Patillas balance is executed and no missing release, treatment withdrawal, evaporation, or operational-loss term is imputed.
