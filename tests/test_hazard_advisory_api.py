from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.backend.hazard_advisory_api as hazard_api


def client() -> TestClient:
    app = FastAPI()
    app.include_router(hazard_api.router)
    return TestClient(app)


def test_summary_exposes_causality_and_source_universe_guards(monkeypatch):
    monkeypatch.setattr(hazard_api, "load_records", lambda: [])
    monkeypatch.setattr(hazard_api, "load_relationships", lambda: [])
    monkeypatch.setattr(hazard_api, "load_manifestations", lambda: [])
    monkeypatch.setattr(hazard_api, "graph_integrity", lambda: {"state": "PASS", "unresolved": []})

    response = client().get("/hazards/summary")
    assert response.status_code == 200
    body = response.json()
    assert "is not causation" in body["scope"]["statement"]
    assert body["source_universe"]["completeness_claimed"] is False
    assert any("Causal confirmation" in guard for guard in body["semantic_guards"])


def test_empty_materialization_is_not_promoted_to_complete(monkeypatch):
    monkeypatch.setattr(hazard_api, "load_records", lambda: [])
    response = client().get("/hazards/events")
    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}


def test_sources_endpoint_preserves_open_denominator():
    response = client().get("/hazards/sources")
    assert response.status_code == 200
    body = response.json()
    assert body["certification_state"] == "OPEN"
    assert body["completeness_claimed"] is False
    assert body["unresolved_material"]
