# Puerto Rico Baseline Grid

Canonical file: `registry/spatial/pr_grid_full_cell_index_saturated.csv`

- Rows: 98,304
- Columns: 13
- Grid rows: 256
- Grid columns: 384
- Cell size: 4 x 4 pixels
- Logical pixel canvas: 1536 x 1024
- SHA256: `17733f3f18c8a644e31c1eb25fb27b73b4bf353c6de57d5203c4311e05d64483`
- Coordinate domain: `IMAGE_PIXEL`
- Geographic status: `PIXEL_CONTEXT_ONLY`

## Authority boundary

`Cell_ID`, `Row_Index`, `Column_Index`, pixel bounds, pixel centroids, pixel counts,
`Land_Pixel_Ratio`, and `Classification` are valid only in the canonical image-pixel
coordinate frame represented by this CSV.

The current baseline has **no certified world-space binding**. The following values are
therefore intentionally unresolved and MUST NOT be inferred from Puerto Rico boundaries,
municipios, coastlines, screenshots, or a rejected reconstruction:

- CRS
- geographic bounds
- affine/geotransform
- source-raster SHA256
- longitude/latitude-to-`Cell_ID` transform

`geographic_assignment_enabled` is false. A longitude/latitude record MUST NOT be assigned
to a `Cell_ID` unless a separate, independently certified world-binding derivative is later
introduced with its own provenance and validation receipt.

Run the pixel-grid structural validator with:

```bash
python scripts/validate_pr_grid.py --require-sha
```

This validation certifies the pixel ledger only; it does not certify geographic placement.
