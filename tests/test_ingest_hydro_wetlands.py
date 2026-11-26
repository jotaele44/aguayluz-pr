"""scripts/ingest_hydro_wetlands.py offline, on polygons copied from the real NWI service.

Needs shapely; skipped where it is not installed.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from aguayluz import hydro_inventory as hi  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "hydro_inventory" / "infra"

_SPEC = importlib.util.spec_from_file_location("ingest_hydro_wetlands", REPO / "scripts" / "ingest_hydro_wetlands.py")
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def run(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "geo").mkdir(parents=True)
    shutil.copy(REPO / "data" / "geo" / "pr_watersheds.geojson", data / "geo" / "pr_watersheds.geojson")
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg = json.loads((REPO / "config" / hi.SOURCES_CONFIG).read_text(encoding="utf-8"))
    next(s for s in cfg["live_sources"] if s["source_key"] == "usfws_nwi")["min_rows"] = 1
    (cfg_dir / hi.SOURCES_CONFIG).write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    code = ingest.main(["--src-dir", str(FIXTURES), "--data-dir", str(data), "--config-dir", str(cfg_dir),
                        "--now", "2026-11-15T14:30:00Z"])
    assert code == 0
    return data


def test_wetlands_ponds_and_exclusions_follow_the_nwi_type(tmp_path):
    data = run(tmp_path)
    rows = hi.read_claims(data / hi.HYDRO_DIR / "claims_nwi.jsonl")
    retained = [c for c in rows if c["disposition"] == "RETAINED"]
    by_type = {c["attributes"]["wetland_type"]: c["feature_type"] for c in retained}
    assert by_type["Freshwater Pond"] == by_type["Lake"] == "waterbody"
    assert by_type["Freshwater Emergent Wetland"] == by_type["Estuarine and Marine Wetland"] == "wetland"
    reasons = {c["attributes"]["wetland_type"]: c["exclusion_reason"] for c in rows if c["disposition"] == "EXCLUDED"}
    assert reasons["Riverine"].startswith("riverine channel")
    assert reasons["Estuarine and Marine Deepwater"].startswith("open estuarine or marine water")
    assert reasons["NA"] == "no wetland type in the source"
    assert any(c["exclusion_reason"] == ingest.OUTSIDE for c in rows)
    assert all(c["attributes"]["huc8"] for c in retained)


def test_the_ledger_closes_and_tiles_stay_under_budget(tmp_path):
    data = run(tmp_path)
    receipt = json.loads((data / hi.HYDRO_DIR / "ingest_wetlands_receipt.json").read_text())
    ledger = receipt["ledgers"]["usfws_nwi"]
    assert ledger["source"] == ledger["retained"] + ledger["excluded"] and ledger["delta"] == 0
    assert "1980s" in receipt["vintage"]
    tiles = sorted((data / "geo" / "wetlands").glob("*.geojson"))
    assert tiles and all(p.stat().st_size <= ingest.GEO_FILE_BUDGET_BYTES for p in tiles)
    for p in tiles:
        doc = json.loads(p.read_text())
        assert all(f["properties"]["huc8"] == p.stem for f in doc["features"])


def test_committed_wetland_tiles_are_strict_json_and_within_budget():
    tiles = sorted((REPO / "data" / "geo" / "wetlands").glob("*.geojson"))
    assert tiles
    for p in tiles:
        assert p.stat().st_size <= ingest.GEO_FILE_BUDGET_BYTES
        json.loads(p.read_text(), parse_constant=lambda c, name=p.name: pytest.fail(f"{name} holds {c}"))
