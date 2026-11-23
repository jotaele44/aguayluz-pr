"""scripts/ingest_hydro_nhd.py offline, on features copied from the real NHD, WBD and SDWIS responses.

Needs shapely for simplification; skipped where it is not installed.
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
FIXTURES = REPO / "tests" / "fixtures" / "hydro_inventory"

_SPEC = importlib.util.spec_from_file_location("ingest_hydro_nhd", REPO / "scripts" / "ingest_hydro_nhd.py")
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def prepared(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    for name in ("nwps_gauge_state.jsonl", "utility_assets.jsonl"):
        shutil.copy(REPO / "data" / name, data / name)
    return data


def run(data, src=FIXTURES):
    return ingest.main(["--src-dir", str(src), "--data-dir", str(data), "--now", "2026-11-15T02:00:00Z"])


def test_reaches_are_claimed_coastline_is_excluded_and_gnis_ids_are_unpadded(tmp_path):
    data = prepared(tmp_path)
    assert run(data) == 0
    flows = hi.read_claims(data / hi.HYDRO_DIR / "claims_nhd_flowlines.jsonl")
    assert len(flows) == 10
    coast = [c for c in flows if c["disposition"] == "EXCLUDED"]
    assert len(coast) == 2 and {c["exclusion_reason"] for c in coast} == {"coastline, not a watercourse"}
    # canal/ditch reaches (FType 336) are claimed as canals, every other retained reach as a stream
    assert {c["feature_type"] for c in flows if c["attributes"]["ftype"] == "336"} == {"canal"}
    assert {c["feature_type"] for c in flows if c["attributes"]["ftype"] != "336"} == {"stream"}
    named = [c for c in flows if c["attributes"].get("gnis_id")]
    assert named and all(not c["attributes"]["gnis_id"].startswith("0") for c in named)
    receipt = json.loads((data / hi.HYDRO_DIR / "ingest_surface_receipt.json").read_text())
    assert receipt["ledgers"]["usgs_nhd_flowlines"]["delta"] == 0
    assert all(size <= ingest.GEO_FILE_BUDGET_BYTES for size in receipt["geometry_bytes"].values())


def test_intakes_have_no_location_and_nws_gauges_carry_their_usgs_id(tmp_path):
    data = prepared(tmp_path)
    assert run(data) == 0
    intakes = hi.read_claims(data / hi.HYDRO_DIR / "claims_sdwis_intakes.jsonl")
    assert len(intakes) == 5 and all(c["lat"] is None for c in intakes)
    gauges = hi.read_claims(data / hi.HYDRO_DIR / "claims_nwps_gauges.jsonl")
    assert len(gauges) == 118 and sum(1 for c in gauges if c["attributes"].get("usgs_site_no")) >= 100
    sheds = hi.read_claims(data / hi.HYDRO_DIR / "claims_wbd.jsonl")
    assert {c["attributes"]["level"] for c in sheds} == {"huc8", "huc10"}


def test_an_empty_flowline_feed_stops_the_run(tmp_path):
    # CONSTRUCTED: The National Map returns no flowlines at all.
    src = tmp_path / "src"
    shutil.copytree(FIXTURES, src)
    for page in (src / "nhd_flow").glob("page_*.json"):
        page.write_text('{"type":"FeatureCollection","features":[]}')
    data = prepared(tmp_path)
    assert run(data, src) == 1
    receipt = json.loads((data / hi.HYDRO_DIR / "ingest_surface_receipt.json").read_text())
    assert receipt["last_status"] == "FAIL" and "no features" in receipt["last_error"]
