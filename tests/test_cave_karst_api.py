"""Contract tests for the read-only cave and karst monitor API."""
from __future__ import annotations

from copy import deepcopy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.cave_karst_api as cave_api  # noqa: E402
from server.backend.app import app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from aguayluz.cave_karst import compute_record_hash  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_summary_is_explicitly_pilot_scoped(client):
    body = client.get("/cave-karst/summary").json()

    assert body["scope"]["statewide_complete"] is False
    assert body["scope"]["registry_scope"] == {"pilot": 4}
    assert "pilot" in body["scope"]["statement"].lower()
    assert "complete" in body["scope"]["statement"].lower()
    assert body["counts"] == {
        "assets": 4,
        "sources": 4,
        "edges": 6,
        "status_events": 3,
        "observations": 2,
        "alerts": 3,
        "unresolved_gaps": body["counts"]["unresolved_gaps"],
    }
    assert body["validation"] == {
        "ok": True,
        "error_count": 0,
        "contradiction_count": 0,
    }


def test_asset_list_exposes_required_monitor_fields(client):
    body = client.get("/cave-karst/assets").json()

    assert body["total"] == 4
    park = next(item for item in body["items"] if item["asset_id"] == "AYL_KARST_CAMUY_PARK")
    assert park["current_status"] == "closed"
    assert park["status_quality"] == "verified"
    assert park["conflict_hold"] is False
    assert park["freshness"]["status_as_of"]
    assert park["confidence"] == 85
    assert park["evidence_tier"] == "T2"
    assert park["hydrologic"]["roles"]
    assert park["infrastructure"]["condition"] == "unknown"
    assert park["unresolved_gaps"]
    assert park["coordinates_redacted"] is True
    assert park["lat"] is None and park["lon"] is None


def test_asset_filters_are_exact(client):
    closed = client.get("/cave-karst/assets?status=closed").json()
    assert closed["total"] == 3
    assert {item["current_status"] for item in closed["items"]} == {"closed"}

    cave = client.get("/cave-karst/assets?asset_kind=cave").json()
    assert [item["asset_id"] for item in cave["items"]] == [
        "AYL_KARST_CAMUY_CUEVA_CLARA"
    ]

    review = client.get("/cave-karst/assets?review_status=needs_review").json()
    assert {item["asset_id"] for item in review["items"]} == {
        "AYL_KARST_CAMUY_CUEVA_CLARA",
        "AYL_KARST_CAMUY_RIVER_SYSTEM",
    }


def test_nonpublic_coordinates_are_redacted_even_when_present(client, monkeypatch):
    registry = deepcopy(cave_api._load_registry())
    park = registry["assets"][0]
    park["lat"] = 18.361
    park["lon"] = -66.817
    park["location_disclosure"] = "public_generalized"
    monkeypatch.setattr(cave_api, "_load_registry", lambda: registry)

    body = client.get(f"/cave-karst/assets/{park['asset_id']}").json()
    assert body["coordinates_redacted"] is True
    assert body["lat"] is None
    assert body["lon"] is None


def test_public_exact_coordinates_require_p0_public(client, monkeypatch):
    registry = deepcopy(cave_api._load_registry())
    park = registry["assets"][0]
    park["lat"] = 18.361
    park["lon"] = -66.817
    park["privacy_class"] = "P0_PUBLIC"
    park["location_disclosure"] = "public_exact"
    monkeypatch.setattr(cave_api, "_load_registry", lambda: registry)

    body = client.get(f"/cave-karst/assets/{park['asset_id']}").json()
    assert body["coordinates_redacted"] is False
    assert body["lat"] == 18.361
    assert body["lon"] == -66.817


def test_p1_public_exact_is_still_redacted(client, monkeypatch):
    registry = deepcopy(cave_api._load_registry())
    park = registry["assets"][0]
    park["lat"] = 18.361
    park["lon"] = -66.817
    park["privacy_class"] = "P1_GENERALIZED"
    park["location_disclosure"] = "public_exact"
    monkeypatch.setattr(cave_api, "_load_registry", lambda: registry)

    body = client.get(f"/cave-karst/assets/{park['asset_id']}").json()
    assert body["coordinates_redacted"] is True
    assert body["lat"] is None and body["lon"] is None


@pytest.mark.parametrize(
    "privacy_class",
    ["P1_GENERALIZED", "P2_CONTROLLED", "P3_RESTRICTED"],
)
def test_public_api_strips_sensitive_references(client, monkeypatch, privacy_class):
    registry = deepcopy(cave_api._load_registry())
    park = registry["assets"][0]
    park["privacy_class"] = privacy_class
    park["lat"] = 18.361
    park["lon"] = -66.817
    park["legal"]["parcel_refs"] = ["SENSITIVE-PARCEL"]
    park["culture"]["heritage_registry_refs"] = ["SENSITIVE-HERITAGE"]
    park["emergency"]["plan_ref"] = "CONTROLLED-PLAN"
    park["emergency"]["evacuation_route_ref"] = "CONTROLLED-ROUTE"
    park["emergency"]["muster_point_ref"] = "CONTROLLED-MUSTER"
    park["monitoring"]["sensor_ids"] = ["SEN_CAMUY_STAGE_01"]
    park["monitoring"]["site_ids"] = ["AYL_KARST_CAMUY_MON_01"]

    observation = next(
        item for item in registry["observations"] if item["asset_id"] == park["asset_id"]
    )
    observation["sensor_id"] = "SEN_CAMUY_STAGE_01"
    observation["monitoring_site_id"] = "AYL_KARST_CAMUY_MON_01"
    monkeypatch.setattr(cave_api, "_load_registry", lambda: registry)

    body = client.get(f"/cave-karst/assets/{park['asset_id']}").json()
    assert body["lat"] is None and body["lon"] is None
    assert body["legal"]["parcel_refs"] == []
    assert body["culture"]["heritage_registry_refs"] == []
    assert body["emergency"]["plan_ref"] is None
    assert body["emergency"]["evacuation_route_ref"] is None
    assert body["emergency"]["muster_point_ref"] is None
    assert body["monitoring"]["sensor_ids"] == []
    assert body["monitoring"]["site_ids"] == []
    assert all("sensor_id" not in item for item in body["observations"])
    assert all("monitoring_site_id" not in item for item in body["observations"])
    if privacy_class == "P3_RESTRICTED":
        assert body["canonical_name"] == "Restricted cave/karst resource"
        assert body["aliases"] == []


def test_stale_api_status_fails_closed_to_unknown(client, monkeypatch):
    registry = deepcopy(cave_api._load_registry())
    park = registry["assets"][0]
    registry["events"] = [
        item for item in registry["events"] if item["asset_id"] != park["asset_id"]
    ]
    park["operational"]["status"] = "open"
    park["operational"]["status_as_of"] = "2025-01-01T00:00:00Z"
    monkeypatch.setattr(cave_api, "_load_registry", lambda: registry)

    body = client.get(f"/cave-karst/assets/{park['asset_id']}").json()
    assert body["current_status"] == "unknown"
    assert body["status_quality"] == "stale"
    assert body["conflict_hold"] is False


def test_conflicting_api_evidence_blocks_false_open(client, monkeypatch):
    registry = deepcopy(cave_api._load_registry())
    park = registry["assets"][0]
    existing_hashes = [item["record_hash"] for item in registry["events"]]
    event = {
        "event_id": "AYL_KEVT_CAMUY_API_CONFLICT_20260808",
        "asset_id": park["asset_id"],
        "event_type": "status_observation",
        "observed_at": "2026-08-08T04:20:00Z",
        "effective_from": "2026-08-08T04:20:00Z",
        "effective_to": None,
        "from_status": "unknown",
        "to_status": "open",
        "reason": "Synthetic API contradiction fixture.",
        "source_ref": "SRC_KARST_CTPR_REOPEN_20210317",
        "evidence_tier": "T2",
        "confidence": 60,
        "review_status": "accepted",
        "supersedes_event_id": None,
        "recorded_at": "2026-08-08T04:20:01Z",
        "previous_hash": registry["events"][-1]["record_hash"],
        "record_hash": "",
    }
    event["record_hash"] = compute_record_hash(event)
    registry["events"].append(event)
    monkeypatch.setattr(cave_api, "_load_registry", lambda: registry)

    body = client.get(f"/cave-karst/assets/{park['asset_id']}").json()
    assert body["current_status"] == "unknown"
    assert body["status_quality"] == "conflicting"
    assert body["conflict_hold"] is True
    assert [item["record_hash"] for item in registry["events"][:-1]] == existing_hashes


def test_asset_detail_binds_alerts_observations_edges_and_sources(client):
    body = client.get("/cave-karst/assets/AYL_KARST_CAMUY_PARK").json()

    assert body["asset_id"] == "AYL_KARST_CAMUY_PARK"
    assert body["alerts"]
    assert body["edge_count"] >= 1
    assert body["source_count"] >= 1
    assert isinstance(body["observations"], list)
    assert client.get("/cave-karst/assets/NO_SUCH_ASSET").status_code == 404


def test_status_history_is_append_only_ordered_for_display(client):
    body = client.get(
        "/cave-karst/assets/AYL_KARST_CAMUY_PARK/status-history"
    ).json()

    assert body["asset_id"] == "AYL_KARST_CAMUY_PARK"
    assert body["total"] >= 1
    assert all(item["record_hash"].startswith("sha256:") for item in body["items"])
    timestamps = [
        item.get("effective_from") or item.get("observed_at") or ""
        for item in body["items"]
    ]
    assert timestamps == sorted(timestamps, reverse=True)


def test_provenance_and_graph_edges_are_asset_scoped(client):
    provenance = client.get(
        "/cave-karst/assets/AYL_KARST_CAMUY_PARK/provenance"
    ).json()
    assert provenance["total"] >= 3
    assert all(item["source_id"].startswith("SRC_KARST_") for item in provenance["items"])
    assert all(item["url"].startswith("https://") for item in provenance["items"])

    edges = client.get("/cave-karst/assets/AYL_KARST_CAMUY_PARK/edges").json()
    assert edges["total"] >= 1
    assert {item["direction"] for item in edges["items"]} <= {"inbound", "outbound"}


def test_alert_filters_preserve_derived_severity(client):
    body = client.get("/cave-karst/alerts?severity_min=3").json()
    assert body["items"]
    assert all(item["severity"] >= 3 for item in body["items"])

    access = client.get(
        "/cave-karst/alerts?alert_type=public_access_restriction"
    ).json()
    assert access["total"] == 3
    assert {item["alert_type"] for item in access["items"]} == {
        "public_access_restriction"
    }


def test_cave_karst_surface_is_read_only(client):
    assert client.post("/cave-karst/summary").status_code == 405
    assert client.patch("/cave-karst/assets/AYL_KARST_CAMUY_PARK").status_code == 405
    assert client.delete("/cave-karst/alerts").status_code == 405

    cave_paths = {
        path: methods
        for path, methods in app.openapi()["paths"].items()
        if path.startswith("/cave-karst")
    }
    assert cave_paths
    assert {method for methods in cave_paths.values() for method in methods} == {"get"}
