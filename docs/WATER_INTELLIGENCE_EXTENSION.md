# AguaYLuz Water Intelligence Extension

## Active vector

`IMPORT_PRI_GPKG_LAYERS → IMPORT_PRASA_INTAKES_OUTFALLS_AND_WATERWORKS → IMPORT_NID_DAM_REGISTRY → BUILD_TREATMENT_AND_WASTEWATER_ENTITIES → CONSTRUCT_WATERSHED_RELATIONSHIP_GRAPH → GENERATE_CONTINUITY_RISK_ENGINE → EXPORT_FEDERATION_READY_WATER_INTELLIGENCE`

## New scripts

- `scripts/import_local_hydro_assets.py`
- `scripts/build_water_relationship_graph.py`
- `scripts/export_water_intelligence.py`

## Expected local run

```bash
python scripts/import_local_hydro_assets.py \
  --src "/Users/jotaele/Documents/Data/Energy_Sector/PRI.gpkg" \
  --src "/Users/jotaele/Documents/Data/Energy_Sector/Acueductos & Canales de Riego" \
  --src "/Users/jotaele/Documents/Data/Energy_Sector/NID"
python scripts/build_water_relationship_graph.py
python scripts/federation_export.py
python scripts/export_water_intelligence.py
pytest -q
```

## Output extension streams

- `data/water_relationships.jsonl`
- `data/continuity_risks.jsonl`
- `exports/federation/water_intelligence/water_assets.jsonl`
- `exports/federation/water_intelligence/water_relationships.jsonl`
- `exports/federation/water_intelligence/continuity_risks.jsonl`
- `exports/federation/water_intelligence/manifest.json`
