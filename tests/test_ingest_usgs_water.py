import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_usgs_water import (  # noqa: E402
    build_rows,
    classify,
    merge,
    municipality_for,
    parse_rdb,
)

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "usgs_pr_sites_sample.rdb"

# A simple square covering the Guajataca damsite (~18.40, -66.92) for PIP tests.
_SQUARE = [[-67.0, 18.3], [-67.0, 18.5], [-66.8, 18.5], [-66.8, 18.3], [-67.0, 18.3]]
MUNIS = [("Quebradillas", [_SQUARE])]


def test_parse_rdb_skips_comments_and_format_line():
    rows = parse_rdb(FIXTURE.read_text())
    assert len(rows) == 15
    assert rows[0]["site_no"] == "50010800"
    assert rows[0]["site_tp_cd"] == "LK"


def test_classify_reservoir_canal_and_gage():
    assert classify("LK", "LAGO GUAJATACA AT DAMSITE, PR")[0] == "reservoir"
    assert classify("LK", "LEVITTOWN LAKE 1, TOA BAJA, PR")[0] == "lake"
    assert classify("ST-CA", "CANAL DE PATILLAS AT INTAKE 113, PR")[0] == "irrigation_canal"
    assert classify("ST", "RIO PIEDRAS AT HATO REY, PR")[0] == "stream_gage"


def test_municipality_point_in_polygon():
    assert municipality_for(18.398, -66.922, MUNIS) == "Quebradillas"
    assert municipality_for(18.0, -65.0, MUNIS) == "unknown"  # outside the square


def test_build_rows_are_schema_shaped_and_authoritative():
    sites = parse_rdb(FIXTURE.read_text())
    rows = build_rows(sites, MUNIS)
    assert len(rows) == 15
    r = next(x for x in rows if x["asset_id"] == "USGS_50010800")
    assert r["asset_type"] == "water" and r["asset_subtype"] == "reservoir"
    assert r["evidence_tier"] == "T1" and r["review_status"] == "accepted"
    assert r["operator"] == "USGS" and r["confidence"] == 80
    assert r["municipality"] == "Quebradillas"  # resolved by PIP
    assert 17.7 <= r["lat"] <= 18.7 and -67.95 <= r["lon"] <= -65.2


def test_rows_validate_against_utility_asset_schema():
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas" / "utility_asset.schema.json").read_text()
    )
    rows = build_rows(parse_rdb(FIXTURE.read_text()), MUNIS)
    required = set(schema["required"])
    allowed = set(schema["properties"])
    enums = {k: set(v["enum"]) for k, v in schema["properties"].items() if "enum" in v}
    for r in rows:
        assert required <= set(r), f"missing fields in {r['asset_id']}"
        assert set(r) <= allowed, f"extra fields in {r['asset_id']}"
        for k, choices in enums.items():
            if k in r:
                assert r[k] in choices


def test_merge_preserves_non_usgs_and_replaces_usgs():
    existing = [
        {"asset_id": "PWR00001", "asset_type": "power"},
        {"asset_id": "WTR_1", "asset_type": "water"},
        {"asset_id": "USGS_50010800", "asset_type": "water", "confidence": 1},
    ]
    new = [{"asset_id": "USGS_50010800", "asset_type": "water", "confidence": 80}]
    out = {r["asset_id"]: r for r in merge(existing, new)}
    assert set(out) == {"PWR00001", "WTR_1", "USGS_50010800"}
    assert out["USGS_50010800"]["confidence"] == 80  # replaced
