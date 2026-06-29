# Spatial Overlay Join Rules

Use the shared Puerto Rico baseline grid to prevent spatial-format drift across federation repos. Domain-specific geography must resolve to `Cell_ID` before cross-repo promotion.

## Rules

1. Do not fork the grid schema per repo.
2. Do not use municipality or barrio as the primary federation spatial key.
3. Preserve `Cell_ID`, `Row_Index`, and `Column_Index` in every derived overlay.
4. Store overlay provenance with source name, source URL or file, run timestamp, and confidence method when available.
5. Treat overlays as many-to-many when boundaries cross cell edges.
6. Use `Land_Pixel_Ratio` and `Classification` for filtering only.
7. Hub rollups should join producer outputs through `Cell_ID` first, then enrich with overlay labels.
