"""Tests for the Centinelas handoff receiver: receipt + promotion, both idempotent."""

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "ingest_centinelas_handoff",
    Path(__file__).resolve().parent.parent / "scripts" / "ingest_centinelas_handoff.py",
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

SIGNAL = {
    "schema_version": "1.0",
    "item_id": "w1",
    "source_url": "https://example.pr/prasa-boil",
    "title": "PRASA boil water advisory for Ponce",
    "published_at": "2026-07-15T00:00:00+00:00",
    "captured_at": "2026-07-15T01:00:00+00:00",
    "confidence": 0.8,
    "domain_tags": ["potable_water", "boil_water"],
    "municipality": "Ponce",
    "labels": ["ENVIRONMENTAL"],
}
ENVELOPE = {
    "item_id": "w1",
    "target": "aguayluz-pr",
    "idempotency_key": "centinelas:w1:aguayluz-pr:deadbeefdeadbeefdead",
    "signal": SIGNAL,
}


def _run(tmp_path, monkeypatch, envelope=ENVELOPE, expected_target="aguayluz-pr"):
    """Invoke main() the way the workflow does, against tmp paths."""
    events = tmp_path / "service_events.jsonl"
    monkeypatch.setenv("CENTINELAS_CLIENT_PAYLOAD", json.dumps(envelope))
    monkeypatch.setenv("EXPECTED_TARGET", expected_target)
    monkeypatch.setattr(
        "sys.argv",
        ["ingest_centinelas_handoff.py",
         "--receipts-dir", str(tmp_path / "receipts"),
         "--events-out", str(events)],
    )
    rc = mod.main()
    rows = [json.loads(line) for line in events.read_text().splitlines() if line.strip()] \
        if events.exists() else []
    return rc, rows


def test_handoff_writes_receipt_and_promotes_signal(tmp_path, monkeypatch):
    rc, rows = _run(tmp_path, monkeypatch)
    assert rc == 0

    receipts = list((tmp_path / "receipts").glob("*.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())["idempotency_key"] == ENVELOPE["idempotency_key"]

    # The signal reached the corpus through the same mapping the dispatch path uses.
    assert len(rows) == 1
    assert rows[0]["event_type"] == "boil_water"
    assert rows[0]["evidence_tier"] == "T3"
    assert rows[0]["review_status"] == "needs_review"
    assert rows[0]["municipality"] == "Ponce"


def test_redelivery_is_a_no_op(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch)
    rc, rows = _run(tmp_path, monkeypatch)

    assert rc == 0
    assert len(list((tmp_path / "receipts").glob("*.json"))) == 1
    assert len(rows) == 1, "a duplicate delivery must not append a second event"


def test_envelope_without_signal_stores_receipt_only(tmp_path, monkeypatch):
    envelope = {k: v for k, v in ENVELOPE.items() if k != "signal"}
    rc, rows = _run(tmp_path, monkeypatch, envelope=envelope)

    assert rc == 0
    assert len(list((tmp_path / "receipts").glob("*.json"))) == 1
    assert rows == []


def test_target_mismatch_aborts_before_any_write(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(tmp_path, monkeypatch, expected_target="thehub-pr")
    assert not (tmp_path / "receipts").exists()


def test_step_outputs_reported_to_github_output(tmp_path, monkeypatch):
    github_output = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    _run(tmp_path, monkeypatch)

    written = dict(
        line.split("=", 1) for line in github_output.read_text().splitlines() if "=" in line
    )
    assert written["duplicate"] == "false"
    assert written["promoted_event_id"].startswith("AYL_EVT_20260715_")
