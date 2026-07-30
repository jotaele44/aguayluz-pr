# Puerto Rico Boundary Validation Contract

`data/geo/pr_municipios.geojson` is a Census-derived visualization layer. It must not be treated as authoritative or decision-relevant merely because GeoPandas can read it.

The gating command is:

```bash
python scripts/validate_pr_geo_boundaries.py \
  data/geo/pr_municipios.geojson \
  --registry data/geo/pr_municipios.json \
  --output-class authoritative \
  --report outputs/pr_geo_validation.json
```

A nonzero exit status means `FAILED_VALIDATION`. The output must not be promoted, certified, or described as complete.

## CRS policy

The validator reads raw GeoJSON metadata before loading the layer through GeoPandas.

- `authoritative` and `decision_relevant` layers with no declared CRS fail immediately.
- No CRS is silently assigned to an authoritative layer.
- `synthetic` or `experimental` layers may use `--assume-crs` only when a positive `--positional-uncertainty-m` is also supplied.
- An assumed CRS keeps the output non-authoritative.

## Independent validation classes

The report always names these classes separately:

1. `GEOMETRY_VALIDITY`
   - non-null and non-empty geometry
   - polygon or multipolygon type
   - Shapely geometry validity
2. `LAYER_RELATIONSHIP_TOPOLOGY`
   - polygon coverage validity
   - overlap area threshold
   - cross-feature containment
   - narrow internal-gap detection
3. `NETWORK_GRAPH_TOPOLOGY`
   - adjacency requires a shared boundary segment, not point contact
   - non-island municipios must form one connected component
   - only Culebra (`72049`) and Vieques (`72147`) may be isolated
4. `ADMINISTRATIVE_BOUNDARY_TOPOLOGY`
   - exactly 78 municipio records
   - unique five-digit GEOIDs with Puerto Rico prefix `72`
   - unique names matching `data/geo/pr_municipios.json`
   - every Census internal point covered by its named boundary
   - every non-island municipio participates in the adjacency graph

Passing one class does not imply that another class passed. A generic `TOPOLOGY_PASSED` claim is invalid.

## Provenance and limits

The boundary builder documents the source as U.S. Census Bureau 2023 cartographic boundary files and reprojects output to WGS84. The validation report certifies the committed layer against this repository contract. It does not establish legal-boundary status beyond the supplied Census-derived source lineage.

## CI behavior

`.github/workflows/geo-boundary-validation.yml` runs:

- the focused synthetic regression suite;
- the validator against the committed 78-municipio GeoJSON;
- Python compilation of the validator.

The workflow is read-only and does not regenerate or overwrite geodata.