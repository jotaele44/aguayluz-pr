"""Offline operator-runner tests: candidate discovery and failure receipts."""
import json

import pytest

from scripts import ingest_hydro_intelligence as runner


def test_missing_source_id_is_fail_closed():
    with pytest.raises(ValueError):
        runner.source_record({"source_families": []}, "unknown")


def test_discovery_persists_candidate_only(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"source_families": [{
        "source_id": "eia_860m",
        "index_url": "https://www.eia.gov/electricity/data/eia860m/",
        "artifact_type": "xlsx",
    }]}))
    monkeypatch.setattr(runner, "REGISTRY", registry)
    monkeypatch.setattr(runner, "fetch_artifact", lambda *a, **k: (
        b'<a href="/archive/xls/march_generator2026.xlsx">March</a>', "text/html"))
    assert runner.main(["--source-id", "eia_860m", "--data-root", str(tmp_path / "result")]) == 0
    records = list((tmp_path / "result" / "runs").glob("*.json"))
    assert len(records) == 1
    state = json.loads(records[0].read_text())[0]
    assert state["state"] == "DISCOVERY_ONLY"
    assert state["candidate_count"] == 1
    assert state["completeness"] == "NOT_CLAIMED"


def test_failed_discovery_has_immutable_failure_receipt(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"source_families": [{
        "source_id": "eia_923",
        "index_url": "https://www.eia.gov/electricity/data/eia923/",
        "artifact_type": "zip",
    }]}))
    monkeypatch.setattr(runner, "REGISTRY", registry)

    def fails(*args, **kwargs):
        raise TimeoutError("network unavailable")

    monkeypatch.setattr(runner, "fetch_artifact", fails)
    assert runner.main(["--source-id", "eia_923", "--data-root", str(tmp_path / "result")]) == 2
    record = next((tmp_path / "result" / "runs").glob("*.json"))
    state = json.loads(record.read_text())[0]
    assert state["state"] == "QUARANTINED_NOT_PROMOTED"
    assert state["failure_class"] == "RETRYABLE_TRANSPORT"
