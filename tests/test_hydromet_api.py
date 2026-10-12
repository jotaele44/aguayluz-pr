"""/hydromet/* API over an offline NWPS run (real captures in tests/fixtures/)."""
import importlib.util
import sys
from pathlib import Path

import pytest
import server.backend.hydromet_api as hydromet_api
from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.backend import main as legacy

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def client() -> TestClient:
    app = FastAPI()
    app.include_router(hydromet_api.router)
    return TestClient(app)


@pytest.fixture
def populated(tmp_path, monkeypatch):
    pytest.importorskip("shapely")
    spec = importlib.util.spec_from_file_location("ingest_nwps_gauges_api", REPO / "scripts" / "ingest_nwps_gauges.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.main([
        "--src", str(FIXTURES / "nwps_pr_gauges_sample.json"),
        "--details-src", str(FIXTURES / "nwps_gauge_details"),
        "--data-dir", str(tmp_path), "--assets", str(REPO / "data" / "utility_assets.jsonl"),
    ]) == 0
    monkeypatch.setattr(hydromet_api, "DATA_DIR", tmp_path)
    return tmp_path


def test_empty_plane_reports_never_not_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(hydromet_api, "DATA_DIR", tmp_path)
    body = client().get("/hydromet/summary").json()
    assert body["counts"]["gauges"] == 0
    assert body["scope"]["completeness_claimed"] is False
    assert {s["freshness"]["state"] for s in body["sources"]} == {"NEVER"}
    assert client().get("/hydromet/gauges").json() == {"total": 0, "items": []}


def test_summary_and_sources_expose_freshness_and_provenance(populated):
    body = client().get("/hydromet/summary").json()
    assert body["counts"]["gauges"] == 6 and body["counts"]["gauges_in_flood"] == 1
    assert body["integrity"]["state"] == "PASS"
    assert "not confirmed damage" in body["scope"]["statement"]
    sources = client().get("/hydromet/sources").json()
    nwps = next(s for s in sources["sources"] if s["source_id"] == "nwps_gauges")
    assert nwps["receipt"]["last_status"] == "PASS"
    assert len(nwps["receipt"]["last_success"]["byte_sha256"]) == 64
    assert sources["legacy_catalog"]["url"].endswith("IDP-GISRestMetadata")


def test_gauges_filter_and_geojson(populated):
    flooding = client().get("/hydromet/gauges", params={"flooding_only": "true"}).json()
    assert [g["lid"] for g in flooding["items"]] == ["QUEP4"]
    assert "detail" not in flooding["items"][0]
    everything = client().get("/hydromet/gauges").json()
    assert everything["items"][0]["lid"] == "QUEP4"  # in-flood gauges sort first
    by_town = client().get("/hydromet/gauges", params={"municipio": "aibonito"}).json()
    assert [g["lid"] for g in by_town["items"]] == ["AIBP4"]
    fc = client().get("/hydromet/gauges.geojson").json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 6
    props = next(f["properties"] for f in fc["features"] if f["properties"]["lid"] == "QUEP4")
    assert props["flooding"] is True and props["asset_id"] == "USGS_50010800"


def test_refresh_unknown_source_is_404(tmp_path, monkeypatch):
    monkeypatch.setattr(hydromet_api, "DATA_DIR", tmp_path)
    assert client().post("/hydromet/refresh/nope").status_code == 404


def test_refresh_runs_ingest_then_alerts(tmp_path, monkeypatch):
    monkeypatch.setattr(hydromet_api, "DATA_DIR", tmp_path)
    calls = []

    def fake_run(script, argv):
        calls.append((script.name, argv))
        return {"script": f"scripts/{script.name}", "return_code": 0, "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr(hydromet_api, "_run_script", fake_run)
    response = client().post("/hydromet/refresh/nwps_gauges")
    assert response.status_code == 200 and response.json()["ok"] is True
    assert [name for name, _ in calls] == ["ingest_nwps_gauges.py", "build_alerts.py", "build_alert_system.py"]
    assert calls[0][1] == ["--data-dir", str(tmp_path)]
    status = client().get("/hydromet/refresh/status").json()
    assert status["running"] is False and status["last_result"]["source_id"] == "nwps_gauges"


def test_failed_ingest_stops_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(hydromet_api, "DATA_DIR", tmp_path)
    calls = []

    def failing(script, argv):
        calls.append(script.name)
        return {"script": script.name, "return_code": 1, "stdout_tail": "", "stderr_tail": "bulk fetch failed"}

    monkeypatch.setattr(hydromet_api, "_run_script", failing)
    response = client().post("/hydromet/refresh/nwps_gauges")
    assert response.status_code == 502 and response.json()["ok"] is False
    assert calls == ["ingest_nwps_gauges.py"]


def test_refresh_is_single_flight(tmp_path, monkeypatch):
    monkeypatch.setattr(hydromet_api, "DATA_DIR", tmp_path)
    assert hydromet_api._refresh_lock.acquire(blocking=False)
    try:
        assert client().post("/hydromet/refresh/nwps_gauges").status_code == 409
    finally:
        hydromet_api._refresh_lock.release()


def test_refresh_requires_key_when_auth_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(hydromet_api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(legacy, "_API_KEY", "s3cret-value")
    assert client().post("/hydromet/refresh/nwps_gauges").status_code == 401


def test_run_script_captures_output_and_exit(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text(
        "import sys\n"
        "def main():\n"
        "    print('argv', sys.argv[1:])\n"
        "    return 3\n"
    )
    result = hydromet_api._run_script(script, ["--x", "1"])
    assert result["return_code"] == 3 and "--x" in result["stdout_tail"]
    crashing = tmp_path / "crash.py"
    crashing.write_text("def main():\n    raise RuntimeError('boom')\n")
    assert "boom" in hydromet_api._run_script(crashing, [])["stderr_tail"]
