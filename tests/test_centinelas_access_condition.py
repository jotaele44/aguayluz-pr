from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.ingest_centinelas_access_condition import promote_access_condition, validate_signal
from scripts.ingest_centinelas_handoff import promote_signal, write_receipt


def _signal() -> dict:
    return {
        "schema_version": "1.0",
        "kind": "access_condition",
        "condition_id": "usfs-elyunque-test:abc123",
        "alert_id": "usfs-elyunque-test",
        "authority": "USDA Forest Service",
        "forest": "el_yunque",
        "source_listing_url": "https://www.fs.usda.gov/r08/elyunque/alerts",
        "source_url": "https://www.fs.usda.gov/r08/elyunque/alerts/forest-trails-status",
        "source_hash": "a" * 64,
        "forest_order_identifier": None,
        "published_at": None,
        "last_source_update": None,
        "effective_start": "2026-03-15T00:00:00+00:00",
        "effective_end": None,
        "observed_at": "2026-08-07T20:00:00+00:00",
        "evidence_tier": "T1",
        "scope_type": "trail_segment",
        "scope_name": "El Yunque Trail — Los Picachos spur to peak",
        "asset_key": "elyunque.trail.el_yunque.los_picachos_to_peak",
        "status": "restricted",
        "status_basis": "explicit_official_text",
        "semantic_hash": "b" * 64,
        "confidence": 1.0,
        "restriction_text": "The El Yunque Trail from Los Picachos to the peak is closed.",
        "corroboration": {
            "authority_count": 1,
            "document_count": 2,
            "listing_confirmed": True,
            "detail_confirmed": True,
            "forest_order_confirmed": False,
        },
    }


def test_access_condition_preserves_t1_and_stays_unbound_without_certified_geometry(tmp_path: Path):
    out = tmp_path / "access_conditions.jsonl"
    row = promote_access_condition(_signal(), out)
    assert row["evidence_tier"] == "T1"
    assert row["bound_asset_id"] is None
    assert row["binding_status"] == "unbound_no_certified_geometry"
    persisted = json.loads(out.read_text().strip())
    assert persisted["condition_id"] == row["condition_id"]


def test_geometry_fields_are_rejected():
    signal = _signal()
    signal["geometry"] = {"type": "Point", "coordinates": [-65.8, 18.3]}
    with pytest.raises(ValueError, match="must not carry geometry"):
        validate_signal(signal)


def test_non_t1_access_condition_is_rejected():
    signal = _signal()
    signal["evidence_tier"] = "T3"
    with pytest.raises(Exception):
        validate_signal(signal)


def test_handoff_routes_access_condition_without_service_event_conversion(tmp_path: Path):
    access_out = tmp_path / "access.jsonl"
    service_out = tmp_path / "service.jsonl"
    payload = {
        "kind": "access_condition",
        "item_id": _signal()["condition_id"],
        "target": "aguayluz-pr",
        "idempotency_key": "centinelas:test:aguayluz-pr:123",
        "signal": _signal(),
    }
    event_id, condition_id = promote_signal(payload, service_out, access_out)
    assert event_id is None
    assert condition_id == _signal()["condition_id"]
    assert access_out.exists()
    assert not service_out.exists()


def test_duplicate_receipt_is_idempotent(tmp_path: Path):
    payload = {
        "kind": "access_condition",
        "item_id": _signal()["condition_id"],
        "target": "aguayluz-pr",
        "idempotency_key": "centinelas:test:aguayluz-pr:duplicate",
        "signal": _signal(),
    }
    first_path, first_duplicate = write_receipt(payload, tmp_path)
    second_path, second_duplicate = write_receipt(copy.deepcopy(payload), tmp_path)
    assert first_path == second_path
    assert first_duplicate is False
    assert second_duplicate is True
