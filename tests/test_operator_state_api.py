"""The shipped API must persist edits and expose the same state on every read."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from server.backend import app as canonical
from server.backend import main as backend

ASSET = {"asset_id": "A", "asset_name": "Test asset", "asset_type": "water", "status": "active", "review_status": "accepted", "municipality": "Ponce", "lat": 18.0, "lon": -66.6}
EVENT = {"event_id": "E", "event_type": "outage", "municipality": "Ponce", "start_time": "2026-01-01T00:00:00Z", "review_status": "needs_review"}
REVIEW = {"record_ref": "R", "reason": "Original reason", "severity": "warn"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "OPERATOR_STATE_PATH", tmp_path / "operator.sqlite")
    monkeypatch.setattr(backend, "OUTPUTS", tmp_path)
    monkeypatch.setattr(backend, "_assets", [ASSET.copy()])
    monkeypatch.setattr(backend, "_events", [EVENT.copy()])
    monkeypatch.setattr(backend, "_API_KEY", "")
    (tmp_path / "review_queue.json").write_text(json.dumps({"items": [REVIEW]}))
    with TestClient(canonical.app) as api:
        yield api


def test_asset_edit_reaches_list_map_summaries_and_preserves_source(client):
    reply = client.patch("/assets/A", json={"status": "inactive", "review_status": "blocked"})
    assert reply.status_code == 200
    assert reply.json()["operator_override"]["original_values"] == {"status": "active", "review_status": "accepted"}
    assert client.get("/assets").json()[0]["status"] == "inactive"
    assert client.get("/assets.geojson").json()["features"][0]["properties"]["review_status"] == "blocked"
    assert client.get("/summary/sectors").json()["water"]["active"] == 0
    assert client.get("/summary/coverage").json()["review_status"] == {"blocked": 1}
    assert client.get("/municipios/Ponce/summary").json()["active_assets"] == 0
    assert backend._assets == [ASSET]


def test_printable_report_renders_source_markup_as_literal_text(client, monkeypatch):
    from html.parser import HTMLParser

    class ReportParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []
            self.text = []

        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)

        def handle_data(self, data):
            self.text.append(data)

    raw = '<img src=x onerror="window.report_canary=1"> Á & "Ponce"'
    event = {**EVENT, "municipality": raw, "affected_area": raw,
             "event_type": '<script>alert(1)</script>', "start_time": '<b>today</b>'}
    monkeypatch.setattr(backend, "_events", [event])
    response = client.get("/export/report.html")
    assert response.status_code == 200
    parser = ReportParser()
    parser.feed(response.text)
    assert not {"img", "script", "b"}.intersection(parser.tags)
    assert parser.text.count(raw) == 2
    assert event == backend._events[0]


def test_acknowledgement_is_not_resolution_and_reaches_event_reads(client):
    assert client.patch("/events/E", json={"resolution_status": "acknowledged"}).status_code == 200
    assert client.get("/events/E").json()["resolution_status"] == "acknowledged"
    assert client.get("/events").json()["items"][0]["resolution_status"] == "acknowledged"
    assert client.get("/assets/A/events").json()[0]["resolution_status"] == "acknowledged"
    assert client.patch("/events/E", json={"resolution_status": "resolved"}).status_code == 200
    assert client.get("/events/E").json()["resolution_status"] == "resolved"
    assert backend._events == [EVENT]


def test_active_outage_total_is_computed_before_pagination(client, monkeypatch):
    source = [{**EVENT, "event_id": f"E{i}"} for i in range(701)]
    source += [
        {**EVENT, "event_id": "resolved", "resolution_status": "resolved"},
        {**EVENT, "event_id": "ended", "end_time": "2026-01-02T00:00:00Z"},
        {**EVENT, "event_id": "other", "event_type": "maintenance"},
        {**EVENT, "event_id": "ack", "resolution_status": "acknowledged"},
    ]
    monkeypatch.setattr(backend, "_events", source)
    result = client.get("/events", params={"type": "outage", "active": True, "limit": 0}).json()
    assert result == {"total": 702, "offset": 0, "items": []}
    assert client.patch("/events/E0", json={"resolution_status": "resolved"}).status_code == 200
    assert client.get("/events?type=outage&active=true&limit=1").json()["total"] == 701
    assert client.get("/events?type=outage&active=false&limit=0").json()["total"] == 3
    assert source[0].get("resolution_status") is None


def test_review_decision_only_hides_the_reviewed_source_version(client):
    binding = client.get("/review-queue").json()["items"][0]["review_binding"]
    assert client.post("/review-queue/R/decision", json={"decision": "accept", "source_binding": binding}).status_code == 200
    assert client.get("/review-queue").json()["total"] == 0
    changed = {**REVIEW, "reason": "New contradictory evidence"}
    (backend.OUTPUTS / "review_queue.json").write_text(json.dumps({"items": [changed]}))
    assert client.get("/review-queue").json()["total"] == 1
    stale = client.post("/review-queue/R/decision", json={"decision": "reject", "source_binding": binding})
    assert stale.status_code == 409
    assert backend._operator_store().status()["audit_entries"] == 1


@pytest.mark.parametrize("patch", [[], None, {}, {"asset_id": "B"}, {"status": None}, {"status": "fake"}, {"status": False}])
def test_invalid_asset_edit_never_writes(client, patch):
    assert client.patch("/assets/A", json=patch).status_code == 422
    assert not backend.OPERATOR_STATE_PATH.exists()


def test_duplicate_ids_and_missing_records_fail_closed(client, monkeypatch):
    monkeypatch.setattr(backend, "_assets", [ASSET.copy(), {**ASSET, "asset_name": "Different source row"}])
    assert client.patch("/assets/A", json={"status": "damaged"}).status_code == 409
    assert client.patch("/events/missing", json={"resolution_status": "resolved"}).status_code == 404
    assert not backend.OPERATOR_STATE_PATH.exists()


def test_duplicate_ids_after_refresh_do_not_inherit_override(client, monkeypatch):
    assert client.patch("/assets/A", json={"status": "damaged"}).status_code == 200
    monkeypatch.setattr(backend, "_assets", [ASSET.copy(), {**ASSET, "asset_name": "Different source row"}])
    rows = client.get("/assets").json()
    assert len(rows) == 2
    assert all(row["status"] == "active" and row["operator_override"]["state"] == "UNRESOLVED" for row in rows)


def test_auth_refusal_never_writes(client, monkeypatch):
    monkeypatch.setattr(backend, "_API_KEY", "test-key")
    assert client.patch("/assets/A", json={"status": "damaged"}).status_code == 401
    assert not backend.OPERATOR_STATE_PATH.exists()


def test_storage_failure_is_visible_and_does_not_report_success(client):
    backend.OPERATOR_STATE_PATH.write_bytes(b"invalid database preserved")
    assert client.patch("/assets/A", json={"status": "damaged"}).status_code == 503
    assert client.get("/assets").status_code == 503
    status = client.get("/system/status").json()["operator_state"]
    assert status["state"] == "unavailable"
    assert status["durable"] is False
    assert backend.OPERATOR_STATE_PATH.read_bytes() == b"invalid database preserved"


def test_writes_survive_a_fresh_api_process(tmp_path):
    workspace = tmp_path / "workspace with spaces"
    (workspace / "data").mkdir(parents=True)
    (workspace / "exports").mkdir()
    (workspace / "data" / "utility_assets.jsonl").write_text(json.dumps(ASSET) + "\n")
    (workspace / "data" / "service_events.jsonl").write_text(json.dumps(EVENT) + "\n")
    (workspace / "exports" / "review_queue.json").write_text(json.dumps({"items": [REVIEW]}))
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "AGUAYLUZ_DATA_HOME": str(workspace), "AGUAYLUZ_OPERATOR_STATE_PATH": str(workspace / "operator.sqlite"), "API_SECRET_KEY": "", "PYTHONPATH": str(root / "src") + os.pathsep + str(root)}
    prefix = "from fastapi.testclient import TestClient\nfrom server.backend.app import app\nimport json\nclient = TestClient(app)\n"
    write = prefix + '''
assert client.patch('/assets/A', json={'status': 'damaged'}).status_code == 200
assert client.patch('/events/E', json={'resolution_status': 'acknowledged'}).status_code == 200
binding = client.get('/review-queue').json()['items'][0]['review_binding']
assert client.post('/review-queue/R/decision', json={'decision': 'accept', 'source_binding': binding}).status_code == 200
print('committed')
'''
    read = prefix + '''
assert client.get('/assets').json()[0]['status'] == 'damaged'
assert client.get('/events/E').json()['resolution_status'] == 'acknowledged'
assert client.get('/review-queue').json()['total'] == 0
print(json.dumps(client.get('/system/status').json()['operator_state']))
'''
    first = subprocess.run([sys.executable, "-c", write], env=env, cwd=root, text=True, capture_output=True, timeout=180)
    assert first.returncode == 0, first.stderr
    second = subprocess.run([sys.executable, "-c", read], env=env, cwd=root, text=True, capture_output=True, timeout=180)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["audit_entries"] == 3
