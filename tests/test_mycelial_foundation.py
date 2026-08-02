from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from research.mycelial.foundation import (
    FungalOccurrenceRecord,
    ImportFailedError,
    analytics_unavailable,
    append_adjudication,
    append_duplicate_link,
    append_fungal_occurrence,
    append_policy_decision,
    append_source,
    append_supersession,
    import_records,
    initialize_database,
    register_dataset,
    resolve_effective_occurrence_id,
    safe_fungal_occurrence_view,
    validate_fungal_occurrence,
)


def record(**overrides) -> FungalOccurrenceRecord:
    values = {
        "occurrence_id": "occ-1",
        "source_id": "src-1",
        "source_record_id": "row-1",
        "observed_at": "2026-08-01",
        "taxon_name": "Fungi",
        "latitude": 18.2,
        "longitude": -66.5,
        "evidence_tier": "T3",
        "review_status": "needs_review",
        "coordinate_confidence": "approximate",
        "coordinate_uncertainty_m": 25.0,
        "coordinate_datum": "WGS84",
        "coordinate_method": "reported",
        "taxonomic_confidence": "reported",
        "temporal_precision": "day",
        "evidence_refs": ("photo:sha256:abc",),
    }
    values.update(overrides)
    return FungalOccurrenceRecord(**values)


def seeded_db(tmp_path):
    conn = initialize_database(tmp_path / "fungal-occurrence.sqlite")
    for number in range(1, 5):
        append_source(
            conn,
            source_id=f"src-{number}",
            title=f"test source {number}",
            source_type="fixture",
            input_sha256=str(number - 1) * 64,
        )
    return conn


def test_valid_record_passes_canonical_schema():
    assert validate_fungal_occurrence(record()) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_tier", "T5"),
        ("review_status", "unreviewed"),
        ("coordinate_confidence", "precise"),
        ("coordinate_datum", "EPSG:4326"),
        ("coordinate_method", "guessed"),
        ("taxonomic_confidence", "certain"),
        ("temporal_precision", "week"),
    ],
)
def test_invalid_enums_cannot_be_inserted(tmp_path, field, value):
    conn = seeded_db(tmp_path)
    with pytest.raises(ValueError, match="invalid_fungal_occurrence"):
        append_fungal_occurrence(conn, record(**{field: value}))


@pytest.mark.parametrize(
    ("observed_at", "temporal_precision"),
    [
        ("2026-08-01", "exact"),
        ("2026-08", "day"),
        ("2026", "month"),
        ("2026-08-01", "year"),
        ("unknown", "unknown"),
    ],
)
def test_temporal_format_must_match_precision(
    tmp_path,
    observed_at,
    temporal_precision,
):
    conn = seeded_db(tmp_path)
    with pytest.raises(ValueError, match="invalid_fungal_occurrence"):
        append_fungal_occurrence(
            conn,
            record(
                observed_at=observed_at,
                temporal_precision=temporal_precision,
            ),
        )


def test_exact_timestamp_is_accepted(tmp_path):
    conn = seeded_db(tmp_path)
    item = record(
        observed_at="2026-08-01T12:30:00Z",
        temporal_precision="exact",
    )
    assert append_fungal_occurrence(conn, item).status == "inserted"


def test_coordinates_require_quantitative_uncertainty(tmp_path):
    conn = seeded_db(tmp_path)
    with pytest.raises(ValueError, match="invalid_fungal_occurrence"):
        append_fungal_occurrence(
            conn,
            record(coordinate_uncertainty_m=None),
        )


def test_absent_coordinates_require_unknown_coordinate_metadata(tmp_path):
    conn = seeded_db(tmp_path)
    item = record(
        latitude=None,
        longitude=None,
        coordinate_uncertainty_m=None,
        coordinate_confidence="unknown",
        coordinate_datum="unknown",
        coordinate_method="unknown",
    )
    assert append_fungal_occurrence(conn, item).status == "inserted"


def test_specimen_verified_requires_evidence_reference(tmp_path):
    conn = seeded_db(tmp_path)
    with pytest.raises(ValueError, match="invalid_fungal_occurrence"):
        append_fungal_occurrence(
            conn,
            record(
                taxonomic_confidence="specimen_verified",
                evidence_refs=(),
            ),
        )


def test_payload_fingerprint_is_deterministic():
    first = record(evidence_refs=("b", "a", "a"))
    second = record(evidence_refs=("a", "b"))
    assert first.payload_fingerprint() == second.payload_fingerprint()


def test_exact_source_record_replay_is_idempotent(tmp_path):
    conn = seeded_db(tmp_path)
    item = record()
    assert append_fungal_occurrence(conn, item).status == "inserted"
    assert append_fungal_occurrence(conn, item).status == "replay"
    assert conn.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 1


def test_same_source_record_with_new_occurrence_id_is_replay(tmp_path):
    conn = seeded_db(tmp_path)
    first = record()
    append_fungal_occurrence(conn, first)
    replay = record(occurrence_id="new-generated-id")
    result = append_fungal_occurrence(conn, replay)
    assert result.status == "replay"
    assert result.occurrence_id == first.occurrence_id
    assert conn.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 1


def test_changed_payload_for_same_source_record_is_rejected(tmp_path):
    conn = seeded_db(tmp_path)
    append_fungal_occurrence(conn, record())
    with pytest.raises(
        ValueError,
        match="source_record_or_occurrence_id_conflict",
    ):
        append_fungal_occurrence(
            conn,
            record(taxon_name="Changed assertion"),
        )


def test_cross_source_candidate_is_linked_not_merged(tmp_path):
    conn = seeded_db(tmp_path)
    first = record()
    second = record(
        occurrence_id="occ-2",
        source_id="src-2",
        source_record_id="row-22",
        evidence_refs=("other:sha256:def",),
    )
    append_fungal_occurrence(conn, first)
    result = append_fungal_occurrence(conn, second)
    assert result.status == "inserted"
    assert result.duplicate_candidates_linked == 1
    assert conn.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 2
    link = conn.execute(
        "SELECT link_type,status FROM duplicate_links"
    ).fetchone()
    assert tuple(link) == ("cross_source_candidate", "needs_review")


def test_import_receipt_accounts_for_every_row_transactionally(tmp_path):
    conn = seeded_db(tmp_path)
    receipt = import_records(
        conn,
        source_id="src-1",
        input_bytes=b"fixture",
        records=[
            record(),
            record(),
            record(
                occurrence_id="bad",
                source_id="src-2",
                source_record_id="other",
            ),
        ],
        run_id="run-1",
    )
    assert receipt.records_seen == 3
    assert receipt.records_inserted == 1
    assert receipt.exact_replays_blocked == 1
    assert receipt.duplicate_candidates_linked == 0
    assert receipt.records_rejected == 1
    assert receipt.status == "partial"
    assert conn.execute(
        "SELECT count(*) FROM import_receipts"
    ).fetchone()[0] == 1


def test_import_run_id_is_idempotent(tmp_path):
    conn = seeded_db(tmp_path)
    first = import_records(
        conn,
        source_id="src-1",
        input_bytes=b"fixture",
        records=[record()],
        run_id="run-idempotent",
    )
    second = import_records(
        conn,
        source_id="src-1",
        input_bytes=b"fixture",
        records=[record(occurrence_id="never-read")],
        run_id="run-idempotent",
    )
    assert second == first
    assert conn.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 1


def test_unexpected_import_failure_rolls_back_and_receipts(tmp_path):
    conn = seeded_db(tmp_path)

    def broken_records():
        yield record()
        raise RuntimeError("fixture failure")

    with pytest.raises(ImportFailedError) as exc_info:
        import_records(
            conn,
            source_id="src-1",
            input_bytes=b"broken",
            records=broken_records(),
            run_id="run-failed",
        )
    assert exc_info.value.receipt.status == "failed"
    assert exc_info.value.receipt.error_code == "RuntimeError"
    assert conn.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 0
    stored = json.loads(
        conn.execute(
            "SELECT payload_json FROM import_receipts WHERE run_id=?",
            ("run-failed",),
        ).fetchone()[0]
    )
    assert stored["status"] == "failed"


def test_sensitive_coordinates_require_ledger_policy_decision(tmp_path):
    conn = seeded_db(tmp_path)
    item = record(sensitive=True)
    append_fungal_occurrence(conn, item)

    public = safe_fungal_occurrence_view(conn, item)
    assert public["latitude"] is None
    assert public["longitude"] is None
    assert public["coordinate_policy"] == "withheld_sensitive_taxon"

    append_policy_decision(
        conn,
        decision_id="policy-allow-1",
        subject_type="occurrence",
        subject_id=item.occurrence_id,
        policy="sensitive_coordinate_disclosure",
        outcome="allow_exact_coordinates",
        actor="reviewer:test",
        reason="fixture authorization",
    )
    authorized = safe_fungal_occurrence_view(
        conn,
        item,
        policy_decision_id="policy-allow-1",
    )
    assert authorized["latitude"] == 18.2
    assert authorized["longitude"] == -66.5


def test_irrelevant_policy_decision_does_not_expose_coordinates(tmp_path):
    conn = seeded_db(tmp_path)
    item = record(sensitive=True)
    append_fungal_occurrence(conn, item)
    append_policy_decision(
        conn,
        decision_id="policy-deny-1",
        subject_type="occurrence",
        subject_id=item.occurrence_id,
        policy="sensitive_coordinate_disclosure",
        outcome="deny",
        actor="reviewer:test",
        reason="fixture denial",
    )
    view = safe_fungal_occurrence_view(
        conn,
        item,
        policy_decision_id="policy-deny-1",
    )
    assert view["latitude"] is None


def _append_chain_records(conn):
    items = [
        record(
            occurrence_id=f"chain-{number}",
            source_record_id=f"chain-row-{number}",
            latitude=18.2 + number / 100,
            longitude=-66.5 - number / 100,
        )
        for number in range(1, 4)
    ]
    for item in items:
        append_fungal_occurrence(conn, item)
    return items


def test_supersession_chain_resolves_deterministically(tmp_path):
    conn = seeded_db(tmp_path)
    first, second, third = _append_chain_records(conn)
    append_supersession(
        conn,
        supersession_id="sup-1",
        predecessor_occurrence_id=first.occurrence_id,
        successor_occurrence_id=second.occurrence_id,
        actor="reviewer:test",
        reason="corrected coordinates",
        policy_basis="phase-0-correction-policy",
    )
    append_supersession(
        conn,
        supersession_id="sup-2",
        predecessor_occurrence_id=second.occurrence_id,
        successor_occurrence_id=third.occurrence_id,
        actor="reviewer:test",
        reason="taxonomic correction",
        policy_basis="phase-0-correction-policy",
    )
    assert (
        resolve_effective_occurrence_id(conn, first.occurrence_id)
        == third.occurrence_id
    )


def test_supersession_rejects_missing_targets_and_cycles(tmp_path):
    conn = seeded_db(tmp_path)
    first, second, third = _append_chain_records(conn)
    with pytest.raises(ValueError, match="unknown_occurrence"):
        append_supersession(
            conn,
            supersession_id="sup-missing",
            predecessor_occurrence_id="missing",
            successor_occurrence_id=second.occurrence_id,
            actor="reviewer:test",
            reason="fixture",
            policy_basis="fixture",
        )
    append_supersession(
        conn,
        supersession_id="sup-1",
        predecessor_occurrence_id=first.occurrence_id,
        successor_occurrence_id=second.occurrence_id,
        actor="reviewer:test",
        reason="fixture",
        policy_basis="fixture",
    )
    append_supersession(
        conn,
        supersession_id="sup-2",
        predecessor_occurrence_id=second.occurrence_id,
        successor_occurrence_id=third.occurrence_id,
        actor="reviewer:test",
        reason="fixture",
        policy_basis="fixture",
    )
    with pytest.raises(ValueError, match="supersession_cycle"):
        append_supersession(
            conn,
            supersession_id="sup-cycle",
            predecessor_occurrence_id=third.occurrence_id,
            successor_occurrence_id=first.occurrence_id,
            actor="reviewer:test",
            reason="fixture",
            policy_basis="fixture",
        )


def _populate_every_ledger(conn):
    first, second, third = _append_chain_records(conn)
    append_duplicate_link(
        conn,
        left_occurrence_id=first.occurrence_id,
        right_occurrence_id=second.occurrence_id,
        link_type="manual_candidate",
        reason="fixture",
        actor="reviewer:test",
    )
    append_adjudication(
        conn,
        adjudication_id="adj-1",
        occurrence_id=first.occurrence_id,
        actor="reviewer:test",
        decision="accepted",
        reason="fixture",
    )
    append_policy_decision(
        conn,
        decision_id="policy-1",
        subject_type="occurrence",
        subject_id=first.occurrence_id,
        policy="fixture",
        outcome="allow",
        actor="reviewer:test",
        reason="fixture",
    )
    register_dataset(
        conn,
        dataset_id="dataset-1",
        title="fixture",
        version="1",
        sha256="a" * 64,
        status="registered",
    )
    import_records(
        conn,
        source_id="src-2",
        input_bytes=b"receipt fixture",
        records=[
            record(
                occurrence_id="receipt-occ",
                source_id="src-2",
                source_record_id="receipt-row",
                latitude=18.8,
                longitude=-66.8,
            )
        ],
        run_id="receipt-run",
    )
    append_supersession(
        conn,
        supersession_id="sup-ledger",
        predecessor_occurrence_id=first.occurrence_id,
        successor_occurrence_id=third.occurrence_id,
        actor="reviewer:test",
        reason="fixture",
        policy_basis="fixture",
    )


@pytest.mark.parametrize(
    "table",
    [
        "source_records",
        "occurrences",
        "duplicate_links",
        "adjudications",
        "policy_decisions",
        "dataset_registry",
        "import_receipts",
        "supersessions",
    ],
)
def test_every_ledger_table_denies_update_and_delete(tmp_path, table):
    conn = seeded_db(tmp_path)
    _populate_every_ledger(conn)
    with pytest.raises(sqlite3.IntegrityError, match="append_only"):
        conn.execute(f"UPDATE {table} SET rowid=rowid")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append_only"):
        conn.execute(f"DELETE FROM {table}")
    conn.rollback()


def _route_signature(route):
    return (
        type(route).__qualname__,
        getattr(route, "path", None),
        tuple(sorted(getattr(route, "methods", ()) or ())),
    )


def test_research_app_does_not_mutate_canonical_app():
    from server.backend.app import app as canonical_app

    before = tuple(_route_signature(route) for route in canonical_app.routes)

    from research.mycelial.app import create_app

    research_app = create_app()
    after = tuple(_route_signature(route) for route in canonical_app.routes)
    assert after == before
    assert research_app is not canonical_app
    assert any(
        getattr(route, "path", None) == "/research/mycelial/status"
        for route in research_app.routes
    )
    assert not any(
        getattr(route, "path", None) == "/research/mycelial/status"
        for route in canonical_app.routes
    )


def test_api_status_and_every_analytics_route_fail_closed():
    from research.mycelial.app import create_app

    client = TestClient(create_app())
    status = client.get("/research/mycelial/status")
    assert status.status_code == 200
    assert status.json()["phase"] == 0
    assert status.json()["module"] == "fungal_occurrence_foundation"

    response = client.get("/research/mycelial/analytics/connectivity")
    assert response.status_code == 503
    body = response.json()
    assert body["available"] is False
    assert body["capability"] == "connectivity"
    assert "coordinates" not in json.dumps(body)


def test_analytics_helper_is_fail_closed():
    result = analytics_unavailable("habitat_suitability")
    assert result["available"] is False
    assert result["status"] == "model_not_calibrated"
    assert "score" not in result
