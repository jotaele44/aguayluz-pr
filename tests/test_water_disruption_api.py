from fastapi.testclient import TestClient
from server.backend import main as legacy
from server.backend.app import app


def test_shadow_consumer_routes_are_mounted_and_discoverable():
    client = TestClient(app)
    health = client.get("/monitoring/health")
    assert health.status_code == 200
    assert health.json()["shadow_water_pipeline"] is True
    assert client.get("/water-disruption/validation-queue").status_code == 200
    console = client.get("/water-disruption/console")
    assert console.status_code == 200
    assert "Shadow mode" in console.text


def test_non_shadow_intake_fails_closed():
    client = TestClient(app)
    response = client.post(
        "/water-disruption/intake",
        json={"candidate_id": "x"},
        headers={"Idempotency-Key": "k", "X-Shadow-Mode": "false"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "shadow_mode_required"


def test_incident_listing_disables_notifications():
    client = TestClient(app)
    payload = client.get("/water-disruption/incidents").json()
    assert payload["shadow_mode"] is True
    assert payload["notifications_enabled"] is False


def test_mutating_routes_require_api_key_when_enabled(monkeypatch):
    monkeypatch.setattr(legacy, "_API_KEY", "test-secret")
    client = TestClient(app)
    requests = [
        ("/water-disruption/intake", {"candidate_id": "x"}),
        (
            "/water-disruption/validation/x",
            {"candidate": {"candidate_id": "x"}, "reviewer": "test"},
        ),
        (
            "/water-disruption/incidents/x/transition",
            {"to_state": "confirmed", "reason": "test"},
        ),
        (
            "/water-disruption/incidents/x/merge",
            {"source_incident_ids": ["y"], "reason": "test"},
        ),
        (
            "/water-disruption/incidents/x/split",
            {"child_dedup_keys": ["child"], "reason": "test"},
        ),
        ("/water-disruption/retractions", {"candidate_id": "x", "reason": "test"}),
    ]
    for url, payload in requests:
        response = client.post(url, json=payload, headers={"Idempotency-Key": "k"})
        assert response.status_code == 401, url

    authorized = client.post(
        "/water-disruption/intake",
        json={"candidate_id": "x"},
        headers={
            "Authorization": "Bearer test-secret",
            "Idempotency-Key": "k",
            "X-Shadow-Mode": "false",
        },
    )
    assert authorized.status_code == 409
    assert client.get("/water-disruption/validation-queue").status_code == 200
