"""/aquifer/bands over the producer's offline output and hand-written readings.

The registry comes from running scripts/ingest_prdner_well_bands.py offline on the real
capture. The readings are the real depths read on 2026-11-08 (USGS parameter 72019,
provisional) for the five wells; cases that need a shape nobody published (a stale reading,
a 62610 row, a failed receipt) are CONSTRUCTED from them and say so.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Bare `pytest` (as CI runs it) puts only tests/ and src/ on sys.path, so `server` is importable
# only if a module collected earlier put the repo root there. This file sorts before every other
# test that imports `server`, so it must do it itself, as tests/test_backend_alerts_api.py does.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.aquifer_api as aquifer_api  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from aguayluz import aquifer_bands as ab  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
SCHEMAS = REPO / "schemas" / "aquifer-bands" / "v1"
NOW = datetime(2026, 11, 8, 17, 0, tzinfo=timezone.utc)

_SPEC = importlib.util.spec_from_file_location(
    "ingest_prdner_well_bands_api", REPO / "scripts" / "ingest_prdner_well_bands.py"
)
ingest = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ingest
_SPEC.loader.exec_module(ingest)

# site -> (depth ft, class the page shows, ft of headroom to Critical)
TODAY = {
    "175934066364800": (9.08, "optimum", 4.57),
    "180057066311300": (24.65, "observation", 2.25),
    "175734066233300": (16.09, "observation", 1.31),
    "175947066130601": (29.76, "critical", -6.33),
    "175910066155500": (48.03, "operational_adjustment", 3.52),
}


def client() -> TestClient:
    app = FastAPI()
    app.include_router(aquifer_api.router)
    return TestClient(app)


def reading(site, value, day="2026-11-08", *, param="72019", unit="ft", prov=True):
    return {
        "reading_id": f"AYL_RDG_{day.replace('-', '')}_usgscv_{site}_{param}_20261108144500",
        "asset_id": f"USGSGW_{site}", "site_no": site, "metric": "groundwater_level",
        "parameter_code": param, "value": value, "unit": unit, "observed_date": day,
        "provisional": prov, "source_ref": "USGS Water Data API continuous",
    }


def write_readings(data_dir, rows, name="usgs_continuous_readings.jsonl"):
    (data_dir / name).write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.fixture
def populated(tmp_path, monkeypatch):
    assert ingest.main([
        "--src", str(FIXTURES / "prdner_hydro_conditions_selected_wells.html.txt"),
        "--data-dir", str(tmp_path), "--assets", str(FIXTURES / "prdner_usgsgw_assets.jsonl"),
        "--now", "2026-11-08T16:00:00Z",
    ]) == 0
    monkeypatch.setattr(aquifer_api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(aquifer_api, "_now", lambda: NOW)
    return tmp_path


def body():
    response = client().get("/aquifer/bands")
    assert response.status_code == 200
    return response.json()


# ── empty / partial states ────────────────────────────────────────────────────
def test_an_empty_data_dir_reports_never_not_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(aquifer_api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(aquifer_api, "_now", lambda: NOW)
    data = body()
    assert data["items"] == []
    assert data["source"]["freshness"]["state"] == "NEVER" and data["source"]["receipt"] is None
    assert data["counts"] == {
        "wells": 0, "with_reading": 0, "provisional_readings": 0, "stale_readings": 0, "critical": 0}
    assert data["scope"]["completeness_claimed"] is False


def test_bands_are_served_without_any_reading_and_no_class_is_claimed(populated):
    data = body()
    assert [i["site_no"] for i in data["items"]] == list(TODAY)
    for item in data["items"]:
        assert len(item["bands"]) == 5 and item["axis_max_ft"] > item["critical_onset_ft"]
        assert item["reading"] is None and item["class"] is None and item["margin_to_critical_ft"] is None
        assert item["reference_url"].startswith("https://groundwaterwatch.usgs.gov/AWLSites.asp?S=")
        assert item["municipality"] and len(item["source_byte_sha256"]) == 64
    assert data["counts"]["with_reading"] == 0 and data["counts"]["critical"] == 0
    assert data["source"]["freshness"]["state"] == "FRESH"


# ── real readings ─────────────────────────────────────────────────────────────
def test_todays_readings_are_classified_as_the_page_shows_them(populated):
    write_readings(populated, [reading(s, v) for s, (v, _, _) in TODAY.items()])
    data = body()
    by_site = {i["site_no"]: i for i in data["items"]}
    for site, (depth, cls, margin) in TODAY.items():
        item = by_site[site]
        assert item["class"] == cls, site
        assert item["reading"]["value_ft"] == depth
        assert item["margin_to_critical_ft"] == margin
        assert item["reading"]["provisional"] is True and item["reading"]["stale"] is False
    assert by_site["175947066130601"]["class_label"] == "Critical"
    assert data["counts"] == {
        "wells": 5, "with_reading": 5, "provisional_readings": 5, "stale_readings": 0, "critical": 1}


def test_scope_states_what_the_numbers_are_and_are_not(populated):
    scope = body()["scope"]
    assert scope["evidence_tier"] == "T2" and scope["effective_date"] is None
    assert scope["effective_date_status"] == "not_published_by_source"
    assert scope["alerting"] == "display_only" and "provisional" in scope["alerting_reason"]
    assert "not an alert" in scope["statement"] and "provisional" in scope["statement"]
    assert scope["parameter_code"] == "72019"


def test_a_62610_or_wrong_unit_row_never_becomes_a_class(populated):
    """CONSTRUCTED. 62610 is level ABOVE datum: reading 5.0 as depth would call a 29.76 ft well optimum."""
    write_readings(populated, [
        reading("175947066130601", 5.0, "2026-11-09", param="62610"),
        reading("175947066130601", 5.0, "2026-11-09", unit="m"),
        reading("175947066130601", 29.76),
    ])
    item = next(i for i in body()["items"] if i["site_no"] == "175947066130601")
    assert item["class"] == "critical" and item["reading"]["value_ft"] == 29.76


def test_an_old_reading_is_flagged_stale_but_still_shown(populated):
    """CONSTRUCTED: the newest reading is five days old."""
    write_readings(populated, [reading("175947066130601", 29.76, "2026-11-03")])
    data = body()
    item = next(i for i in data["items"] if i["site_no"] == "175947066130601")
    assert item["reading"]["stale"] is True and item["class"] == "critical"
    assert data["counts"]["stale_readings"] == 1


def test_the_daily_value_file_is_used_when_there_is_no_continuous_file(populated):
    write_readings(populated, [{**reading("175910066155500", 48.03), "reading_id": "AYL_RDG_20261108_175910066155500_gw"}],
                   name="groundwater_levels.jsonl")
    item = next(i for i in body()["items"] if i["site_no"] == "175910066155500")
    assert item["class"] == "operational_adjustment"


# ── source health ─────────────────────────────────────────────────────────────
def test_source_freshness_goes_stale_then_failed(populated, monkeypatch):
    monkeypatch.setattr(aquifer_api, "_now", lambda: NOW + timedelta(days=30))
    assert body()["source"]["freshness"]["state"] == "STALE"

    receipt_path = populated / ab.RECEIPT_FILE
    receipt = json.loads(receipt_path.read_text())
    receipt.update(last_status="FAIL", last_error="the page no longer parses")
    receipt_path.write_text(json.dumps(receipt))
    monkeypatch.setattr(aquifer_api, "_now", lambda: NOW)
    data = body()
    assert data["source"]["freshness"]["state"] == "FAILED"
    assert data["source"]["receipt"]["last_error"] == "the page no longer parses"
    assert len(data["items"]) == 5, "a failed run must not hide the last verified bands"


# ── shape of the surface ──────────────────────────────────────────────────────
def test_the_surface_is_read_only():
    methods = {m for route in aquifer_api.router.routes for m in route.methods}
    assert methods <= {"GET", "HEAD"}
    assert {route.path for route in aquifer_api.router.routes} == {"/aquifer/bands"}


def test_the_route_is_served_by_the_shipped_app(populated):
    """Requested through server.backend.app, not read off its route table: this FastAPI does not
    flatten included routers into app.routes (the hydromet routes are absent there too)."""
    app_module = pytest.importorskip("server.backend.app")
    shipped = TestClient(app_module.app)
    response = shipped.get("/aquifer/bands")
    assert response.status_code == 200
    assert [i["site_no"] for i in response.json()["items"]] == list(TODAY)
    assert shipped.get("/aquifer/not-a-route").status_code == 404


def test_the_committed_registry_is_valid_and_served():
    """The registry CI and the desktop app start from: five wells, schema-valid, hash-bearing."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((SCHEMAS / "aquifer_band_registry.schema.json").read_text())
    rows = ab.read_jsonl(REPO / "data" / ab.REGISTRY_FILE)
    assert rows, "data/aquifer_band_registry.jsonl must be committed"
    for row in rows:
        jsonschema.Draft202012Validator(schema).validate(row)
    current = ab.current_registry(rows)
    assert set(current) == set(TODAY)

    original = aquifer_api.DATA_DIR
    try:
        aquifer_api.DATA_DIR = REPO / "data"
        data = client().get("/aquifer/bands").json()
    finally:
        aquifer_api.DATA_DIR = original
    assert len(data["items"]) == 5
    assert all((i["class"] is None) == (i["reading"] is None) for i in data["items"])
