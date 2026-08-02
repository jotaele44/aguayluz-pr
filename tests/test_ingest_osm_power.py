import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_osm_power import (  # noqa: E402
    build_rows,
    load_municipios,
    merge,
    plant_subtype,
    representative_point,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
SCHEMA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())
MUNIS = load_municipios(ROOT / "data" / "geo" / "pr_municipios.geojson")


def _src(tmp_path):
    # adapter reads files named <stem>.geojson; map the plant fixture to power_plant.geojson
    shutil.copy(FIX / "osm_power_plant_sample.geojson", tmp_path / "power_plant.geojson")
    shutil.copy(FIX / "power_substation_point.geojson", tmp_path / "power_substation_point.geojson")
    shutil.copy(FIX / "power_line.geojson", tmp_path / "power_line.geojson")
    return tmp_path


def test_representative_point_handles_geometries():
    assert representative_point({"type": "Point", "coordinates": [-66.1, 18.4]}) == (18.4, -66.1)
    lat, lon = representative_point({"type": "Polygon", "coordinates": [
        [[-66.0, 18.0], [-66.0, 18.2], [-65.8, 18.0], [-66.0, 18.0]]]})
    assert 18.0 <= lat <= 18.2 and -66.0 <= lon <= -65.8
    latlon = representative_point({"type": "LineString", "coordinates": [
        [-66.0, 18.2], [-66.1, 18.25], [-66.2, 18.3]]})
    assert latlon == (18.25, -66.1)  # midpoint vertex


def test_plant_subtype_from_source():
    assert plant_subtype({"source": "wind"}) == "generation (wind)"
    assert plant_subtype({"method": "photovoltaic"}) == "generation (photovoltaic)"


def test_build_rows_maps_all_layers(tmp_path):
    rows = build_rows(_src(tmp_path), MUNIS)
    by_id = {r["asset_id"]: r for r in rows}
    # plants
    pl = by_id["OSMP_-17141575"]
    assert pl["asset_type"] == "power" and pl["asset_subtype"] == "generation (wind)"
    assert pl["operator"] == "Punta Lima Wind Farm, LLC"
    assert pl["evidence_tier"] == "T3" and pl["review_status"] == "needs_review"
    assert "lat" in pl and 17.7 <= pl["lat"] <= 18.7
    # substation (named transmission)
    ss = by_id["OSMS_5296781724"]
    assert ss["asset_subtype"] == "substation" and ss["asset_name"] == "Aguadilla TC"
    # line
    ln = by_id["OSML_401"]
    assert ln["asset_subtype"] == "transmission_line" and ln["geometry_type"] == "line"


def test_rows_validate_against_utility_asset_schema(tmp_path):
    rows = build_rows(_src(tmp_path), MUNIS)
    req = set(SCHEMA["required"])
    allowed = set(SCHEMA["properties"])
    enums = {k: set(v["enum"]) for k, v in SCHEMA["properties"].items() if "enum" in v}
    assert len(rows) == 6  # 3 plants + 2 substations + 1 line
    for r in rows:
        assert req <= set(r) and set(r) <= allowed
        for k, choices in enums.items():
            if k in r:
                assert r[k] in choices


def test_merge_preserves_non_osm_and_replaces_osm():
    existing = [
        {"asset_id": "PWR00001", "asset_type": "power"},
        {"asset_id": "USGS_50059000", "asset_type": "water"},
        {"asset_id": "OSMP_-17141575", "asset_type": "power", "confidence": 1},
    ]
    new = [{"asset_id": "OSMP_-17141575", "asset_type": "power", "confidence": 45}]
    out = {r["asset_id"]: r for r in merge(existing, new)}
    assert set(out) == {"PWR00001", "USGS_50059000", "OSMP_-17141575"}
    assert out["OSMP_-17141575"]["confidence"] == 45  # OSM replaced; others preserved
