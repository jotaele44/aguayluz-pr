"""Regression gates for source identity, complete snapshots and hazard lifecycle."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aguayluz.alert_promotion.weather import weather_alert

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nws_snapshot", ROOT / "scripts/ingest_nws_alerts.py")
nws = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nws)
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def feature(identity="urn:oid:2.49.0.1.840.0.aaaaaaaa.001.1", **fields):
    return {"type": "Feature", "geometry": None, "properties": {
        "id": identity, "status": "Actual", "event": "Flash Flood Warning",
        "effective": "2026-10-04T20:00:00Z", "expires": "2026-10-05T01:00:00Z",
        "areaDesc": "Ponce", "severity": "Severe", **fields,
    }}


def snapshot(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def test_full_ids_and_promoted_ids_remain_distinct():
    rows = nws.build_events(snapshot(feature(), feature("urn:oid:2.49.0.1.840.0.bbbbbbbb.001.1")))
    assert len(nws.merge([], rows)) == 2
    assert len({weather_alert(row, {}, now=NOW).alert_id for row in rows}) == 2
    assert all(row["event_type"] == "unknown" and len(row["source_hash"]) == 64 for row in rows)


def test_empty_complete_snapshot_retires_without_losing_history():
    row = nws.build_events(snapshot(feature()))[0]
    other = {"event_id": "AYL_EVT_20261004_OTHER", "source_ref": "urn:unrelated"}
    result = nws.merge([row, other], [], observed_at=NOW.isoformat())
    retired = next(item for item in result if item["event_id"] == row["event_id"])
    assert weather_alert(retired, {}, now=NOW).status == "closed"
    assert other in result
    assert nws.merge(result, [], observed_at=NOW.isoformat()) == result


@pytest.mark.parametrize("doc", [{}, {"features": None}, {"features": [None]},
    {"features": [], "pagination": {"next": "https://example.test/page2"}},
    snapshot(feature(id="")), snapshot(feature(effective="not-a-date")),
    snapshot(feature(expires="2026-10-04T21:00:00"))])
def test_incomplete_or_malformed_snapshot_fails_closed(doc):
    with pytest.raises((ValueError, TypeError)):
        nws.build_events(doc)


def test_duplicates_fail_instead_of_silent_aggregation():
    rows = nws.build_events(snapshot(feature(), feature()))
    with pytest.raises(ValueError, match="Duplicate"):
        nws.merge([], rows)


def test_expiration_cancel_and_test_controls():
    expired = nws.build_events(snapshot(feature(expires="2026-10-04T21:00:00Z")))[0]
    assert weather_alert(expired, {}, now=NOW).status == "closed"
    current = nws.build_events(snapshot(feature()))[0]
    assert weather_alert(current, {}, now=NOW).status == "active"
    cancelled = nws.build_events(snapshot(feature(messageType="Cancel")))[0]
    assert weather_alert(cancelled, {}, now=NOW).status == "closed"
    assert nws.build_events(snapshot(feature(status="Test"))) == []


def test_source_bytes_and_previous_ledger_are_frozen(tmp_path, monkeypatch):
    raw = json.dumps(snapshot(feature()), indent=3).encode()
    source = tmp_path / "source.json"
    source.write_bytes(raw)
    out = tmp_path / "events.jsonl"
    out.write_bytes(b"")
    monkeypatch.setattr("sys.argv", ["ingest_nws_alerts", "--src", str(source), "--out", str(out)])
    assert nws.main() == 0
    archive = tmp_path / "nws_snapshots"
    assert next(archive.glob("source_*.json")).read_bytes() == raw
    receipt = json.loads(next(archive.glob("receipt_*.json")).read_text())
    assert receipt["feature_count"] == receipt["retained_count"] + receipt["excluded_non_actual_count"]
    before = out.read_bytes()
    source.write_text('{"error":"upstream failure"}')
    with pytest.raises(ValueError):
        nws.main()
    assert out.read_bytes() == before


def test_expired_api_and_export_are_noncritical(monkeypatch):
    from server.backend import main
    spec = importlib.util.spec_from_file_location("nws_export", ROOT / "scripts/federation_export.py")
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    row = {"alert_id": "expiry-probe", "status": "active", "severity": 5,
           "end_at": "2020-01-01T00:00:00Z"}
    monkeypatch.setattr(main, "_alerts", [row])
    assert not main._alert_is_actionable(row)
    assert not exporter._alert_is_critical(5, "active", row["end_at"])
    assert main._project_alerts()[0]["status"] == "closed"
    assert main._project_alerts()[0]["source_status"] == "active"
    assert row["status"] == "active"
