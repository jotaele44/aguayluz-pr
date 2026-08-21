from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.environmental_exposure_api as exposure_api  # noqa: E402
from server.backend.app import app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    stores = {
        "environmental_entity": [
            {
                "entity_id": "ENV_1",
                "entity_kind": "LUST_SITE",
                "name_raw": "Fixture LUST",
                "name_normalized": "fixture lust",
                "canonical_name": "Fixture LUST",
                "authority": "DRNA",
                "authority_id": "CASE-1",
                "utility_asset_id": None,
                "municipality": "Dorado",
                "valid_from": None,
                "valid_until": None,
                "source_record_ids": ["SRC-1"],
                "review_status": "accepted"
            }
        ],
        "environmental_observation": [],
        "environmental_geometry": [],
        "exposure_relationship": [],
        "environmental_exposure_event": [],
    }

    monkeypatch.setattr(exposure_api, "load", lambda kind: stores[kind])
    monkeypatch.setattr(
        exposure_api,
        "graph_integrity",
        lambda: {
            "environmental_entity_count": 1,
            "external_entity_count": 0,
            "relationship_count": 0,
            "state_counts": {},
            "state_count_sum": 0,
            "arithmetic_closes": True,
            "error_count": 0,
            "errors": [],
            "certification_state": "PASS",
        },
    )
    with TestClient(app) as test_client:
        yield test_client


def test_summary_is_read_only_and_fail_closed(client):
    body = client.get("/environmental-exposure/summary").json()
    assert "discovery-only" in body["scope"]["statement"]
    assert body["counts"] == {
        "entities": 1,
        "observations": 0,
        "geometries": 0,
        "relationships": 0,
        "events": 0,
    }
    assert body["integrity"]["certification_state"] == "PASS"
    assert client.post("/environmental-exposure/summary").status_code == 405


def test_entity_detail_and_unknown_identity(client):
    body = client.get("/environmental-exposure/entities/ENV_1").json()
    assert body["entity"]["authority_id"] == "CASE-1"

    missing = client.get("/environmental-exposure/entities/DOES_NOT_EXIST")
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "environmental_entity_not_found"
