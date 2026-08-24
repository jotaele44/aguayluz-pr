from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import server.backend.cave_karst_api as cave_api
from aguayluz.cave_karst import compute_record_hash, load_default_registry
from server.backend.app import app
from starlette.testclient import TestClient

AS_OF = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def test_validation_failure_blocks_operational_projection(monkeypatch) -> None:
    registry = deepcopy(load_default_registry())
    registry["assets"][0].pop("privacy_class")
    monkeypatch.setattr(cave_api, "_load_registry", lambda: registry)
    with TestClient(app) as client:
        response = client.get("/cave-karst/assets")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "cave_karst_registry_invalid"
    assert detail["operational_state"] == "unknown"
    assert detail["error_count"] >= 1


def test_same_rank_status_tie_fails_closed() -> None:
    registry = load_default_registry()
    events = deepcopy(registry["events"])
    previous_hash = events[-1]["record_hash"]
    base = {
        "asset_id": "AYL_KARST_CAMUY_PARK",
        "event_type": "status_observation",
        "observed_at": "2026-08-08T11:00:00Z",
        "effective_from": "2026-08-08T11:00:00Z",
        "effective_to": None,
        "from_status": "unknown",
        "reason": "Synthetic unresolved same-rank tie fixture.",
        "source_ref": "SRC_KARST_CTPR_REOPEN_20210317",
        "evidence_tier": "T2",
        "confidence": 60,
        "review_status": "accepted",
        "supersedes_event_id": None,
        "recorded_at": "2026-08-08T11:00:01Z",
    }
    first = {
        **base,
        "event_id": "AYL_KEVT_CAMUY_V12_TIE_A",
        "to_status": "open",
        "previous_hash": previous_hash,
        "record_hash": "",
    }
    first["record_hash"] = compute_record_hash(first)
    second = {
        **base,
        "event_id": "AYL_KEVT_CAMUY_V12_TIE_B",
        "to_status": "closed",
        "previous_hash": first["record_hash"],
        "record_hash": "",
    }
    second["record_hash"] = compute_record_hash(second)
    events.extend([first, second])

    assert "AYL_KARST_CAMUY_PARK" in cave_api._unresolved_tie_assets(events, AS_OF)
    park = next(
        item
        for item in cave_api.materialize_v11_status(
            registry["assets"], events, as_of=AS_OF
        )
        if item["asset_id"] == "AYL_KARST_CAMUY_PARK"
    )
    assert park["current_status"] == "unknown"
    assert park["status_quality"] == "conflicting"
    assert park["conflict_hold"] is True


def test_statewide_completion_uses_valid_schema_scope_literal() -> None:
    validation = {"ok": True}
    assert cave_api._statewide_complete(
        Counter({"statewide_validated": 4}), validation
    ) is True
    assert cave_api._statewide_complete(Counter({"statewide": 4}), validation) is False
    assert cave_api._statewide_complete(Counter({"pilot": 4}), validation) is False
    assert cave_api._statewide_complete(
        Counter({"statewide_validated": 4}), {"ok": False}
    ) is False


def test_comms_loss_never_emits_safe_or_open_action() -> None:
    alerts = cave_api.evaluate_replay_sample({"comms_loss": True})
    assert alerts == [
        {
            "alert_type": "communications_loss",
            "severity": 2,
            "action": "mark_telemetry_degraded",
            "ruleset_version": cave_api.RULESET_VERSION,
        }
    ]
    assert all("safe" not in item["action"] and "open" not in item["action"] for item in alerts)


def test_camuy_v12_operational_boundary_remains_closed_and_noncommissioned() -> None:
    registry = load_default_registry()
    park = next(
        item
        for item in cave_api.materialize_v11_status(
            registry["assets"], registry["events"], as_of=AS_OF
        )
        if item["asset_id"] == "AYL_KARST_CAMUY_PARK"
    )
    assert park["current_status"] == "closed"
    assert park["conflict_hold"] is False

    public = cave_api.public_asset_projection(park)
    assert cave_api.validate_public_projection(public) == []
    assert public["privacy_class"] == "P1_GENERALIZED"
    assert public["lat"] is None and public["lon"] is None
    assert public["monitoring"]["sensor_ids"] == []
    assert public["monitoring"]["site_ids"] == []
