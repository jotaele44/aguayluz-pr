from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from scripts.ingest_centinelas_handoff import (
    _promote_access_condition,
    _validate_access_signal,
    promote_signal,
    write_receipt,
)


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
    row = _promote_access_condition(_signal(), out)
    assert row["evidence_tier"] == "T1"
    assert row["bound_asset_id"] is None
    assert row["binding_status"] == "unbound_no_certified_geometry"
    persisted = json.loads(out.read_text().strip())
    assert persisted["condition_id"] == row["condition_id"]


def test_geometry_fields_are_rejected():
    signal = _signal()
    signal["geometry"] = {"type": "Point", "coordinates": [-65.8, 18.3]}
    with pytest.raises(ValueError, match="must not carry geometry"):
        _validate_access_signal(signal)


def test_non_t1_access_condition_is_rejected():
    signal = _signal()
    signal["evidence_tier"] = "T3"
    with pytest.raises(ValidationError):
        _validate_access_signal(signal)


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


# --- Re-sent unchanged conditions (heartbeat) -------------------------------
# Centinelas re-sends an unchanged condition under a new idempotency key every
# poll. Only a change of meaning, or a confirmation older than the heartbeat
# interval, is recorded.


def _resend(observed_at: str, key: str, semantic_hash: str = "b" * 64) -> dict:
    signal = _signal()
    signal["observed_at"] = observed_at
    signal["semantic_hash"] = semantic_hash
    signal["source_hash"] = key[-1] * 64
    return {
        "kind": "access_condition",
        "item_id": signal["condition_id"],
        "target": "aguayluz-pr",
        "idempotency_key": f"centinelas:test:aguayluz-pr:{key}",
        "signal": signal,
    }


def _deliver(tmp_path: Path, monkeypatch, payload: dict) -> dict:
    """Run main() the way the workflow does and return its GITHUB_OUTPUT values."""
    from scripts import ingest_centinelas_handoff as mod

    gh_out = tmp_path / "gh_output"
    gh_out.write_text("")
    monkeypatch.setenv("CENTINELAS_CLIENT_PAYLOAD", json.dumps(payload))
    monkeypatch.setenv("EXPECTED_TARGET", "aguayluz-pr")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setattr(
        "sys.argv",
        [
            "ingest_centinelas_handoff.py",
            "--receipts-dir", str(tmp_path / "receipts"),
            "--events-out", str(tmp_path / "service.jsonl"),
            "--access-out", str(tmp_path / "access.jsonl"),
        ],
    )
    assert mod.main() == 0
    return dict(line.split("=", 1) for line in gh_out.read_text().splitlines() if line)


def _rows(tmp_path: Path) -> list[dict]:
    return [json.loads(x) for x in (tmp_path / "access.jsonl").read_text().splitlines() if x]


def _receipts(tmp_path: Path) -> int:
    return len(list((tmp_path / "receipts").glob("*.json")))


def test_first_sighting_is_recorded(tmp_path: Path, monkeypatch):
    out = _deliver(tmp_path, monkeypatch, _resend("2026-11-13T10:00:00+00:00", "k1"))
    assert out["duplicate"] == "false"
    assert out["unchanged"] == "false"
    assert out["promoted_condition_id"] == _signal()["condition_id"]
    assert _receipts(tmp_path) == 1


def test_unchanged_resend_within_heartbeat_writes_nothing(tmp_path: Path, monkeypatch):
    _deliver(tmp_path, monkeypatch, _resend("2026-11-13T10:00:00+00:00", "k1"))
    before = (tmp_path / "access.jsonl").read_bytes()

    out = _deliver(tmp_path, monkeypatch, _resend("2026-11-14T09:59:00+00:00", "k2"))

    # duplicate=true is what lets the workflow's "nothing staged" guard pass.
    assert out["duplicate"] == "true"
    assert out["unchanged"] == "true"
    assert out["promoted_condition_id"] == ""
    assert _receipts(tmp_path) == 1
    assert (tmp_path / "access.jsonl").read_bytes() == before


def test_unchanged_resend_after_heartbeat_refreshes_observed_at(tmp_path: Path, monkeypatch):
    _deliver(tmp_path, monkeypatch, _resend("2026-11-13T10:00:00+00:00", "k1"))

    out = _deliver(tmp_path, monkeypatch, _resend("2026-11-14T10:00:00+00:00", "k2"))

    assert out["duplicate"] == "false"
    assert out["unchanged"] == "false"
    assert _receipts(tmp_path) == 2
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["observed_at"] == "2026-11-14T10:00:00+00:00"


def test_changed_meaning_is_recorded_immediately(tmp_path: Path, monkeypatch):
    _deliver(tmp_path, monkeypatch, _resend("2026-11-13T10:00:00+00:00", "k1"))

    out = _deliver(
        tmp_path, monkeypatch, _resend("2026-11-13T10:15:00+00:00", "k2", semantic_hash="c" * 64)
    )

    assert out["unchanged"] == "false"
    assert _receipts(tmp_path) == 2
    assert _rows(tmp_path)[0]["semantic_hash"] == "c" * 64


def test_unparseable_stored_observation_falls_through_to_a_write(tmp_path: Path, monkeypatch):
    _deliver(tmp_path, monkeypatch, _resend("not-a-time", "k1"))

    out = _deliver(tmp_path, monkeypatch, _resend("2026-11-13T10:15:00+00:00", "k2"))

    assert out["unchanged"] == "false"
    assert _receipts(tmp_path) == 2


def test_late_redelivery_of_a_skipped_resend_cannot_reinstate_an_old_state(
    tmp_path: Path, monkeypatch
):
    # 10:00 restricted is recorded; 10:15 is an unchanged re-send and is skipped
    # (no receipt); 10:30 changes the meaning. A late redelivery of the 10:15 key
    # must not put the superseded state back.
    _deliver(tmp_path, monkeypatch, _resend("2026-11-13T10:00:00+00:00", "k1"))
    skipped = _resend("2026-11-13T10:15:00+00:00", "k2")
    assert _deliver(tmp_path, monkeypatch, skipped)["unchanged"] == "true"
    _deliver(
        tmp_path, monkeypatch, _resend("2026-11-13T10:30:00+00:00", "k3", semantic_hash="c" * 64)
    )

    _deliver(tmp_path, monkeypatch, skipped)

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["semantic_hash"] == "c" * 64
    assert rows[0]["observed_at"] == "2026-11-13T10:30:00+00:00"


def test_out_of_order_older_observation_does_not_replace_newer_row(tmp_path: Path):
    out = tmp_path / "access_conditions.jsonl"
    newer = _signal()
    newer["observed_at"] = "2026-11-13T12:00:00+00:00"
    newer["semantic_hash"] = "c" * 64
    _promote_access_condition(newer, out)

    older = _signal()
    older["observed_at"] = "2026-11-13T11:00:00+00:00"
    kept = _promote_access_condition(older, out)

    assert kept["semantic_hash"] == "c" * 64
    assert json.loads(out.read_text().strip())["semantic_hash"] == "c" * 64
