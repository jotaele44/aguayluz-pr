# PR Pharma Hydrogeologic Model V3 — AguaLuz Internal Staging

This package is intentionally **internal staging**, not a production promotion.

## Invariants

- Original V2 GeoJSON SHA-256: `1a286d6f62b536158a944082965e497fc5bd05870a384c1eb1e8291ab5d2e5d9`
- Original V2 ledger SHA-256: `d0b53c06868ffb9e463e2a5581b4fe9370c0f953d189030f306a99bb8eb6ae29`
- Null parcel, well and SWMU geometries remain null.
- The EPA/FRS coordinate is retained only as a facility point, never a parcel centroid.
- `FEI 2623619` is canonicalized to Vega Baja; the Ceiba alias is retired.
- The FTZ 172-acre area is a regulatory site attribute and is not merged with either cadastral property.
- No groundwater receptor pathway is promoted because the current head-calibration gate fails.

## Files

- `pr_pharma_hydrogeologic_model_v3.geojson`
- `pr_pharma_assets_v3.jsonl`
- `pr_pharma_flow_model_v3.json`
- `crim_parcel_query_05504463104000.json`
- `pr_pharma_ingest_manifest_v3.json`

## Promotion gate

Promotion into `data/utility_assets.jsonl` requires a separate reviewed change after:

1. CRIM/registry parcel geometry is retrieved and deed-area reconciled.
2. Well #3/#5 current status and coordinates are confirmed.
3. A current, aquifer-matched, datum-harmonized head network passes the minimum calibration gate.
