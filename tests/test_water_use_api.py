"""/water-use/estimates over the producer's offline output.

The rows come from running scripts/ingest_usgs_water_use.py offline on the real USGS files.
Cases that need a state nobody published (no data yet, a failed receipt) are CONSTRUCTED.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Bare `pytest` puts only tests/ and src/ on sys.path; see tests/test_aquifer_api.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.water_use_api as water_use_api  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from aguayluz import water_use as wu  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
NOW = "2026-11-14T07:00:00Z"

_SPEC = importlib.util.spec_from_file_location(
    "ingest_usgs_water_use_api", REPO / "scripts" / "ingest_usgs_water_use.py"
)
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)


def client() -> TestClient:
    app = FastAPI()
    app.include_router(water_use_api.router)
    return TestClient(app)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(water_use_api, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def ingested(data_dir):
    assert ingest.main(["--data-dir", str(data_dir), "--now", NOW]) == 0
    return data_dir


def get() -> dict:
    response = client().get("/water-use/estimates")
    assert response.status_code == 200
    return response.json()


def test_three_years_with_the_published_split(ingested):
    body = get()
    years = {y["year"]: y for y in body["years"]}
    assert sorted(years) == [2010, 2015, 2020]
    ps = {y: years[y]["categories"]["public_supply"]["published"] for y in years}
    assert (ps[2020]["surface_water_mgd"], ps[2020]["groundwater_mgd"], ps[2020]["total_mgd"]) == (536.64, 65.1, 601.74)
    assert (ps[2020]["surface_pct"], ps[2020]["groundwater_pct"]) == (89.2, 10.8)
    assert (ps[2015]["surface_pct"], ps[2015]["groundwater_pct"]) == (88.4, 11.6)
    assert ps[2010]["evidence_tier"] == "T2" and ps[2010]["extraction_method"] == "manual_transcription"
    assert years[2010]["categories"]["public_supply"]["restated"]["total_mgd"] == 670.0
    assert body["counts"] == {"records": 207, "years": 3}


def test_scope_says_what_this_is_not(ingested):
    scope = get()["scope"]
    assert scope["completeness_claimed"] is False and scope["alerting"] == "not_applicable"
    assert scope["unit"] == "Mgal/d" and scope["latest_year"] == 2020
    assert scope["evidence_tiers"] == ["T1", "T2"]
    assert "not measurements of current production" in scope["statement"]


def test_total_freshwater_is_served_apart_from_public_supply(ingested):
    year = next(y for y in get()["years"] if y["year"] == 2010)
    fresh = year["categories"]["total_freshwater"]["published"]
    assert (fresh["surface_water_mgd"], fresh["groundwater_mgd"], fresh["total_mgd"]) == (606.14, 117.61, 723.75)
    assert year["categories"]["public_supply"]["published"]["total_mgd"] == 677.21


def test_municipios_restatements_and_sources(ingested):
    body = get()
    assert {k: len(v) for k, v in body["municipios"]["public_supply"].items()} == {"2015": 78, "2020": 78}
    assert list(body["municipios"]["irrigation"]) == ["2015"]
    assert {r["category"] for r in body["restatements"]} == {"public_supply", "total_freshwater"}
    assert all(r["explanation"] is None for r in body["restatements"])
    sources = body["source"]["sources"]
    assert len(sources) == 6 and all(len(s["sha256"]) == 64 for s in sources)
    assert {s["doi"] for s in sources} == {"10.5066/P9HWON2W", "10.5066/P9POVNC6", "10.3133/ofr20141117"}
    assert body["source"]["last_status"] == "PASS" and body["source"]["last_success_utc"] == NOW
    assert body["related"] == {"aquifer_bands": "/aquifer-bands"}
    assert [c["id"] for c in body["categories"]] == list(wu.CATEGORIES)


def test_no_data_yet_is_an_empty_answer_not_an_error(data_dir):
    # CONSTRUCTED: a workspace the producer has never run in.
    body = get()
    assert body["years"] == [] and body["counts"] == {"records": 0, "years": 0}
    assert body["scope"]["latest_year"] is None and body["scope"]["evidence_tiers"] == []
    assert body["source"]["last_status"] is None


def test_a_failed_receipt_is_visible_while_the_last_good_rows_are_served(ingested):
    # CONSTRUCTED: a later run that failed after a success.
    receipt = json.loads((ingested / wu.RECEIPT_FILE).read_text())
    receipt.update(last_status="FAIL", last_error="ps_municipio_2020: SHA-256 differs from the pin")
    (ingested / wu.RECEIPT_FILE).write_text(json.dumps(receipt))
    body = get()
    assert body["source"]["last_status"] == "FAIL" and "differs from the pin" in body["source"]["last_error"]
    assert body["counts"]["records"] == 207


def test_the_router_is_mounted_on_the_real_app():
    app_module = pytest.importorskip("server.backend.app")
    assert "/water-use/estimates" in app_module.app.openapi()["paths"]
