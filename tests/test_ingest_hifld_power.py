import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_hifld_power import (  # noqa: E402
    _status,
    _subtype,
    build_rows,
    load_municipios,
    merge,
    representative_point,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
SCHEMA = json.loads((ROOT / "schemas" / "utility_asset.schema.json").read_text())
MUNIS = load_municipios(ROOT / "data" / "geo" / "pr_municipios.geojson")


def test_status_mapping():
    assert _status("OP") == "active"
    assert _status("IN SERVICE") == "active"
    assert _status("NOT AVAILABLE") == "unknown"
    assert _status("RETIRED") == "inactive"
    assert _status("UNDER CONST") == "planned"


def test_subtype_per_kind():
    assert _subtype("plant", {"PRIM_FUEL": "COAL"}) == "generation (COAL)"
    assert _subtype("substation", {"MAX_VOLT": 230.0}) == "substation (230kV)"
    assert _subtype("substation", {"MAX_VOLT": -999999.0}) == "substation"  # sentinel → plain
    assert _subtype("line", {"VOLT_CLASS": "220-287"}) == "transmission_line (220-287)"


def test_line_midpoint():
    latlon = representative_point({"type": "LineString",
                                   "coordinates": [[-66.23, 17.95], [-66.30, 17.98], [-66.43, 17.99]]})
    assert latlon == (17.98, -66.30)


def test_build_rows_all_three_layers():
    rows = {r["asset_id"]: r for r in build_rows(FIX, MUNIS)}
    pp = rows["HIFLD_PP_62410"]
    assert pp["asset_type"] == "power" and pp["asset_subtype"] == "generation (COAL)"
    assert pp["operator"] == "AES Puerto Rico LP" and pp["evidence_tier"] == "T1"
    assert pp["review_status"] == "accepted" and "lat" in pp
    ss = rows["HIFLD_SS_SS-PR-001"]
    assert ss["asset_subtype"] == "substation (230kV)" and ss["asset_name"] == "BAYAMON TC"
    ss2 = rows["HIFLD_SS_SS-PR-002"]
    assert ss2["status"] == "unknown" and ss2["asset_name"].startswith("Substation")
    tl = rows["HIFLD_TL_TL-PR-01"]
    assert tl["geometry_type"] == "line" and tl["asset_subtype"].startswith("transmission_line")
    assert tl["operator"].startswith("PUERTO RICO ELECTRIC")


def test_rows_validate_against_schema():
    rows = build_rows(FIX, MUNIS)
    assert len(rows) == 5
    req = set(SCHEMA["required"]); allowed = set(SCHEMA["properties"])
    enums = {k: set(v["enum"]) for k, v in SCHEMA["properties"].items() if "enum" in v}
    for r in rows:
        assert req <= set(r) and set(r) <= allowed
        for k, choices in enums.items():
            if k in r:
                assert r[k] in choices
        if "lat" in r:
            assert 17.7 <= r["lat"] <= 18.7 and -67.95 <= r["lon"] <= -65.2


def test_merge_preserves_non_hifld():
    existing = [
        {"asset_id": "OSMP_-1", "asset_type": "power"},
        {"asset_id": "EIA_PLANT_61014", "asset_type": "power"},
        {"asset_id": "HIFLD_PP_62410", "asset_type": "power", "confidence": 1},
    ]
    new = [{"asset_id": "HIFLD_PP_62410", "asset_type": "power", "confidence": 80}]
    out = {r["asset_id"]: r for r in merge(existing, new)}
    assert set(out) == {"OSMP_-1", "EIA_PLANT_61014", "HIFLD_PP_62410"}
    assert out["HIFLD_PP_62410"]["confidence"] == 80
