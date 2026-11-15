"""/hydro/* over the committed inventory, with reading files CONSTRUCTED per test."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.hydro_inventory_api as api  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from aguayluz import hydro_inventory as hi  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
AGUIRRE = "WELL:USGS:175947066130601"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    shutil.copytree(REPO / "data" / "hydro", tmp_path / "hydro")
    (tmp_path / "geo").mkdir()
    shutil.copy(REPO / "data" / "geo" / "pr_aquifers.geojson", tmp_path / "geo" / "pr_aquifers.geojson")
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "_STORE", hi.InventoryStore())
    return tmp_path


def client() -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_summary_states_scope_and_says_when_readings_are_absent(data_dir):
    body = client().get("/hydro/inventory/summary").json()
    assert body["scope"]["completeness_claimed"] is False
    assert body["phase_scope"]["feature_types_enumerated"] == list(hi.FEATURE_TYPES)
    assert body["monitoring"]["readings_present"] is False
    assert set(body["monitoring"]["wells_by_state"]) == {"READINGS_ABSENT_ON_SERVER"}
    assert body["coverage"]["well"]["features_upper"] == 7061
    assert {s["source_key"] for s in body["sources"]} >= {"usgs_monitoring_locations", "usgs_ha730_aquifers_pr"}


def test_monitoring_state_comes_from_the_reading_files_on_the_server(data_dir):
    rows = [{"site_no": "175947066130601", "metric": "groundwater_level", "observed_date": "2026-11-08"},
            {"site_no": "175934066364800", "metric": "groundwater_level", "observed_date": "2019-05-01"}]
    (data_dir / "groundwater_levels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    states = client().get("/hydro/inventory/summary").json()["monitoring"]["wells_by_state"]
    assert states.get("MONITORED_NOW", 0) >= 1 and states.get("HISTORICAL_ONLY", 0) >= 1
    assert "READINGS_ABSENT_ON_SERVER" not in states
    well = client().get(f"/hydro/features/{AGUIRRE}").json()["feature"]
    assert well["monitoring"] == {"state": "MONITORED_NOW", "last_observed_date": "2026-11-08"}


def test_aquifer_filter_separates_coded_wells_from_polygon_only_wells(data_dir):
    coded = client().get("/hydro/aquifer-wells", params={"aquifer": "AQ:USGS_AQFR:110SCPL"}).json()
    assert coded["wells"] == coded["authoritative"] == 145 and coded["polygon_only"] == 0
    polygon = client().get("/hydro/aquifer-wells", params={"aquifer": "AQ:HA730:114:main"}).json()
    assert polygon["wells"] == 0
    with_polygon = client().get("/hydro/aquifer-wells",
                                params={"aquifer": "AQ:HA730:114:main", "include_polygon": "true"}).json()
    assert with_polygon["polygon_only"] == with_polygon["wells"] > 1000
    assert "175947066130601" in with_polygon["site_nos"]


def test_feature_detail_returns_every_claim_link_and_conflict(data_dir):
    body = client().get(f"/hydro/features/{AGUIRRE}").json()
    assert {c["source_key"] for c in body["claims"]} == {"usgs_monitoring_locations", "wqp_wells"}
    assert {lk["to"] for lk in body["links"] if lk["link_type"] == "WELL_IN_AQUIFER"} >= {
        "AQ:USGS_AQFR:110SCPL", "AQ:HA730:114:main"}
    south = client().get("/hydro/features/AQ:HA730:114:main").json()
    assert any(c["attribute"] == "south_coast_aquifer_units" for c in south["conflicts"])


def test_lists_filter_and_page(data_dir):
    aquifers = client().get("/hydro/features", params={"type": "aquifer", "limit": 500}).json()
    assert aquifers["total"] == 159 and all(i["feature_type"] == "aquifer" for i in aquifers["items"])
    page = client().get("/hydro/features", params={"type": "well", "limit": 10, "offset": 20}).json()
    assert page["total"] == 7061 and len(page["items"]) == 10
    assert client().get("/hydro/features", params={"type": "volcano"}).status_code == 422
    assert client().get("/hydro/features/WELL:USGS:000").status_code == 404
    candidates = client().get("/hydro/candidates", params={"type": "well", "tier": "I4"}).json()
    assert candidates["total"] > 0 and all(c["adjudication_state"] == "CANDIDATE_NOT_IDENTITY" for c in candidates["items"])
    assert client().get("/hydro/conflicts").json()["total"] >= 4
    geo = client().get("/hydro/aquifers.geojson")
    assert geo.status_code == 200 and len(geo.json()["features"]) > 100


def test_the_router_is_mounted_on_the_app_ci_boots():
    app_module = pytest.importorskip("server.backend.app")
    paths = app_module.app.openapi()["paths"]
    assert "/hydro/inventory/summary" in paths and "/hydro/aquifer-wells" in paths


def test_aquifer_series_reads_the_server_readings(data_dir):
    # CONSTRUCTED: six Marches of history and one current March for three South Coast coded wells.
    body = client().get("/hydro/aquifer-series", params={"aquifer": "AQ:USGS_AQFR:110SCPL"}).json()
    assert body["readings_present"] is False and body["points"] == []
    sites = [m["site_no"] for m in body["members"]][:3]
    rows = []
    for site in sites:
        for year in range(2015, 2021):
            rows.append({"site_no": site, "metric": "groundwater_level", "parameter_code": "72019", "unit": "ft",
                         "value": 20.0, "observed_date": f"{year}-03-10", "provisional": False})
        rows.append({"site_no": site, "metric": "groundwater_level", "parameter_code": "72019", "unit": "ft",
                     "value": 23.0, "observed_date": "2026-03-10", "provisional": False})
    (data_dir / "usgs_field_measurements_readings.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    body = client().get("/hydro/aquifer-series", params={"aquifer": "AQ:USGS_AQFR:110SCPL"}).json()
    assert body["readings_present"] is True and body["points"][-1] == {
        "month": "2026-03", "n": 3, "wells": sorted(sites), "median_ft": 3.0, "q1_ft": 3.0, "q3_ft": 3.0,
        "membership_changed": False}
    assert "not a water-table elevation" in body["limits"]
    assert client().get("/hydro/aquifer-series", params={"aquifer": "WELL:USGS:175947066130601"}).status_code == 404
