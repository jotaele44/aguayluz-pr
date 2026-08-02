from __future__ import annotations

import json

from fastapi.testclient import TestClient
from research.mycelial.app import app
from research.mycelial.foundation import (
    OccurrenceRecord,
    analytics_unavailable,
    append_occurrence,
    append_source,
    import_records,
    initialize_database,
    safe_occurrence_view,
)


def record(**overrides):
    values = {
        "occurrence_id": "occ-1",
        "source_id": "src-1",
        "observed_at": "2026-08-01",
        "taxon_name": "Fungi",
        "latitude": 18.2,
        "longitude": -66.5,
        "evidence_tier": "T3",
        "coordinate_confidence": "approximate",
        "taxonomic_confidence": "reported",
        "temporal_confidence": "day",
        "evidence_refs": ("photo:sha256:abc",),
    }
    values.update(overrides)
    return OccurrenceRecord(**values)


def seeded_db(tmp_path):
    conn = initialize_database(tmp_path / "mycelial.sqlite")
    append_source(
        conn,
        source_id="src-1",
        title="test source",
        source_type="fixture",
        input_sha256="0" * 64,
    )
    return conn


def test_append_only_deduplication(tmp_path):
    conn = seeded_db(tmp_path)
    item = record()
    assert append_occurrence(conn, item) == "inserted"
    assert append_occurrence(conn, item) == "duplicate"
    assert conn.execute("select count(*) from occurrences").fetchone()[0] == 1


def test_fingerprint_is_deterministic():
    first = record(evidence_refs=("b", "a", "a"))
    second = record(evidence_refs=("a", "b"))
    assert first.fingerprint() == second.fingerprint()


def test_sensitive_coordinates_are_withheld():
    item = record(sensitive=True)
    public = safe_occurrence_view(item)
    assert public["latitude"] is None
    assert public["longitude"] is None
    assert public["coordinate_policy"] == "withheld_sensitive_taxon"
    assert safe_occurrence_view(item, authorized_sensitive=True)["latitude"] == 18.2


def test_import_receipt_accounts_for_every_row(tmp_path):
    conn = seeded_db(tmp_path)
    payload = b"fixture"
    receipt = import_records(
        conn,
        source_id="src-1",
        input_bytes=payload,
        records=[record(), record(), record(occurrence_id="bad", source_id="other")],
        run_id="run-1",
    )
    assert receipt.records_seen == 3
    assert receipt.records_inserted == 1
    assert receipt.duplicates_blocked == 1
    assert receipt.records_rejected == 1
    assert receipt.status == "partial"
    assert conn.execute("select count(*) from import_receipts").fetchone()[0] == 1


def test_incomplete_coordinates_fail_validation(tmp_path):
    conn = seeded_db(tmp_path)
    try:
        append_occurrence(conn, record(longitude=None))
    except ValueError as exc:
        assert "incomplete_coordinates" in str(exc)
    else:
        raise AssertionError("incomplete coordinates were accepted")


def test_analytics_are_fail_closed():
    result = analytics_unavailable("habitat_suitability")
    assert result["available"] is False
    assert result["status"] == "model_not_calibrated"
    assert "score" not in result


def test_api_status_and_every_analytics_route_fail_closed():
    client = TestClient(app)
    status = client.get("/research/mycelial/status")
    assert status.status_code == 200
    assert status.json()["phase"] == 0
    response = client.get("/research/mycelial/analytics/connectivity")
    assert response.status_code == 503
    body = response.json()
    assert body["available"] is False
    assert body["capability"] == "connectivity"
    assert json.dumps(body).find("coordinates") == -1
