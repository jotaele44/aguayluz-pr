from __future__ import annotations

import json
import sqlite3

import pytest

from research.mycelial.phase1_ingest import (
    ANALYTICS_STATUS,
    AUTHORIZATION_REF,
    canonical_payload,
    ingest_jsonl_batch,
    initialize_database,
    raw_batch_bytes,
    training_candidate_only,
)


def source(source_id: str = "MYC_SRC_ALPHA") -> dict:
    return {
        "record_type": "source_registry_entry",
        "schema_version": "1.0.0",
        "source_id": source_id,
        "source_title": f"Fixture {source_id}",
        "authority": "fixture authority",
        "stable_source_record_id_rule": "stable fixture row id",
        "acquisition_design": {
            "method_class": "bounded_file_import",
            "locator_template": "fixture://records/{record_id}",
            "content_hash_algorithm": "sha256",
            "receipt_required": True,
        },
        "license": {
            "license_id": "fixture-license",
            "license_url": "https://example.invalid/license",
            "redistribution": "allowed",
            "derivative_use": "allowed",
            "terms_verified_at": "2026-09-06T00:00:00Z",
        },
        "retention": {
            "raw_bytes": "retain",
            "normalized_records": "retain",
            "minimum_days": 365,
            "deletion_authority": "explicit research-governance decision",
        },
        "attribution": "Fixture only",
        "coordinate_retention_policy": "generalized_only",
    }


def provenance(
    source_id: str = "MYC_SRC_ALPHA",
    provenance_id: str = "MYC_PROV_ALPHA",
    source_record_id: str = "record-alpha",
    duplicate_key: str = "dup-alpha",
) -> dict:
    return {
        "record_type": "provenance_record",
        "schema_version": "1.0.0",
        "provenance_id": provenance_id,
        "source_id": source_id,
        "source_record_id": source_record_id,
        "acquired_at": "2026-09-06T12:00:00Z",
        "content_sha256": "a" * 64,
        "media_type": "structured observation",
        "evidence_tier": "T2",
        "review_state": "admitted",
        "exact_replay_key": f"{source_id}:{source_record_id}",
        "duplicate_candidate_key": duplicate_key,
        "coordinate_representation": {"mode": "generalized", "policy_reference": None},
    }


def taxon() -> dict:
    return {
        "record_type": "taxonomic_evidence",
        "schema_version": "1.0.0",
        "assertion_id": "MYC_TAX_ALPHA",
        "identification_rank": "species",
        "asserted_name": "Pleurotus djamor",
        "verification_class": "media_supported",
        "determiner_id": "OBS_001",
        "determination_date": "2026-09-06",
        "taxonomic_authority": "fixture authority",
        "taxonomic_authority_version": "2026-09-06",
        "synonym_resolution": {
            "input_name": "Pleurotus djamor",
            "accepted_name": "Pleurotus djamor",
            "status": "accepted",
            "basis": "fixture",
        },
        "voucher_ids": [],
        "media_sha256": ["b" * 64],
        "evidence_summary": "Synthetic media-supported fixture.",
        "confidence_basis": "media_morphology",
    }


def survey(*, outcome: str = "positive", completed: bool = True) -> dict:
    return {
        "record_type": "survey_effort",
        "schema_version": "1.0.0",
        "survey_id": "MYC_SUR_ALPHA",
        "protocol_id": "MYC_FIELD_V1",
        "protocol_version": "1.0.0",
        "started_at": "2026-09-06T10:00:00-04:00",
        "ended_at": "2026-09-06T11:00:00-04:00",
        "timezone": "America/Puerto_Rico",
        "search_geometry": {
            "kind": "site_reference",
            "generalized_reference": "fixture-site",
            "exact_coordinates_included": False,
        },
        "person_minutes": 60,
        "observer_count": 1,
        "observer_pseudonyms": ["OBS_001"],
        "qualification_classes": ["field_observer"],
        "target_scope": {"kind": "taxon", "value": "Pleurotus djamor"},
        "coverage": {
            "substrates": ["deadwood"],
            "hosts": [],
            "deadwood": ["fallen log"],
            "microsites": ["shaded"],
        },
        "constraints": [],
        "equipment": ["camera"],
        "outcome": outcome,
        "completed": completed,
        "non_detection_interpretation": (
            "documented non-detection under stated effort; not proof of absence"
        ),
        "outcome_reason": None,
    }


def site() -> dict:
    return {
        "record_type": "lifecycle_site",
        "schema_version": "1.0.0",
        "site_id": "MYC_SITE_ALPHA",
        "stable_site_key": "fixture:alpha",
        "location": {
            "mode": "generalized",
            "municipality": "Trujillo Alto",
            "precision_tier": "municipality",
            "policy_reference": None,
            "latitude": None,
            "longitude": None,
        },
        "habitat_description": "Synthetic shaded deadwood microsite.",
        "created_from_provenance_id": "MYC_PROV_ALPHA",
        "review_state": "needs_review",
    }


def observation(
    observation_id: str = "MYC_OBS_ALPHA",
    observed_at: str = "2026-09-06T10:15:00-04:00",
    state: str = "mature",
) -> dict:
    return {
        "record_type": "lifecycle_observation",
        "schema_version": "1.0.0",
        "observation_id": observation_id,
        "site_id": "MYC_SITE_ALPHA",
        "survey_id": "MYC_SUR_ALPHA",
        "episode_id": "MYC_EPI_ALPHA",
        "observed_at": observed_at,
        "visible_fruiting_state": state,
        "state_basis": "direct visible-fruiting observation",
        "taxonomic_assertion_id": "MYC_TAX_ALPHA",
        "provenance_id": "MYC_PROV_ALPHA",
        "contradiction_state": "none",
        "review_state": "needs_review",
    }


def media() -> dict:
    return {
        "record_type": "media_evidence",
        "schema_version": "1.0.0",
        "media_id": "MYC_MED_ALPHA",
        "observation_id": "MYC_OBS_ALPHA",
        "content_sha256": "c" * 64,
        "media_type": "photo",
        "captured_at": "2026-09-06T10:15:00-04:00",
        "derivative_of": None,
        "license_id": "fixture-license",
        "sensitive_metadata_removed": True,
    }


def temporal(biological_at: str = "2026-09-06T10:15:00-04:00") -> dict:
    return {
        "record_type": "temporal_match",
        "schema_version": "1.0.0",
        "match_id": "MYC_TMP_ALPHA",
        "biological_observed_at": biological_at,
        "observation_timezone": "America/Puerto_Rico",
        "normalization_rule": "compare timezone-aware instants",
        "source_observed_at": "2026-09-06T09:00:00-04:00",
        "source_acquired_at": "2026-09-06T09:05:00-04:00",
        "aggregation_window": "PT1H",
        "lag_window": "PT1H",
        "lead_window": "PT0S",
        "publication_latency": "PT5M",
        "missing_period_behavior": "preserve_missing",
        "temporal_role": "antecedent",
        "future_data_allowed": False,
        "leakage_guard": "source observation must not follow biological observation",
    }


def environmental_sheet() -> dict:
    return {
        "record_type": "environmental_evidence_sheet",
        "schema_version": "1.0.0",
        "predictor_id": "MYC_ENV_RH",
        "scientific_rationale": "Humidity is retained as correlational context only.",
        "interpretation": "correlational_context",
        "source_authority": "fixture provider",
        "product_name": "relative humidity",
        "product_version": "1",
        "units": "percent",
        "scale": "point",
        "resolution": "1 minute",
        "crs": "EPSG:4326",
        "datum": "WGS84",
        "spatial_support": "station",
        "puerto_rico_coverage": "bounded fixture",
        "known_gaps": [],
        "temporal_cadence": "1 minute",
        "latency": "5 minutes",
        "processing_steps": [],
        "uncertainty": "provider quality flags",
        "quality_flags": [],
        "missing_data_behavior": "preserve_missing",
        "license_id": "fixture-license",
        "redistribution": "allowed",
        "reproducible_receipt_design": "freeze source bytes and SHA256",
        "required_fixture_classes": ["positive", "missing", "stale", "contradictory"],
    }


def snapshot() -> dict:
    return {
        "record_type": "environmental_snapshot",
        "schema_version": "1.0.0",
        "snapshot_id": "MYC_SNP_ALPHA",
        "observation_id": "MYC_OBS_ALPHA",
        "predictor_id": "MYC_ENV_RH",
        "temporal_match_id": "MYC_TMP_ALPHA",
        "value": 88.2,
        "unit": "percent",
        "quality_flags": [],
        "provenance_id": "MYC_PROV_ALPHA",
        "review_state": "needs_review",
    }


def full_records() -> list[dict]:
    return [
        source(), provenance(), taxon(), survey(), site(), observation(), media(),
        temporal(), environmental_sheet(), snapshot(),
    ]


def jsonl(records: list[dict]) -> bytes:
    return (
        "\n".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            for record in records
        )
        + "\n"
    ).encode("utf-8")


def test_full_batch_closes_and_preserves_three_manifestations(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    payload = jsonl(full_records())
    receipt = ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_ALPHA", payload=payload
    )
    assert receipt.status == "complete"
    assert receipt.attempted == 10
    assert receipt.accepted == 7
    assert receipt.review_queue == 3
    assert receipt.rejected == 0
    assert receipt.exact_replays == 0
    assert receipt.authorization_ref == AUTHORIZATION_REF
    assert receipt.analytics_status == ANALYTICS_STATUS
    assert raw_batch_bytes(conn, "BATCH_ALPHA") == payload
    assert conn.execute("SELECT count(*) FROM raw_records").fetchone()[0] == 10
    assert conn.execute("SELECT count(*) FROM normalized_records").fetchone()[0] == 10
    assert conn.execute("SELECT count(*) FROM canonical_records").fetchone()[0] == 10


def test_dependency_order_is_independent_of_source_row_order(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    receipt = ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_ALPHA",
        batch_id="BATCH_REVERSED",
        payload=jsonl(list(reversed(full_records()))),
    )
    assert receipt.status == "complete"
    assert receipt.attempted == 10
    assert conn.execute("SELECT count(*) FROM canonical_records").fetchone()[0] == 10


def test_append_only_tables_reject_update(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_ALPHA", payload=jsonl(full_records())
    )
    with pytest.raises(sqlite3.IntegrityError, match="append_only:canonical_records:update"):
        conn.execute("UPDATE canonical_records SET active=0")


def test_exact_replay_is_counted_without_duplicate_canonical_rows(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    payload = jsonl(full_records())
    ingest_jsonl_batch(conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_1", payload=payload)
    receipt = ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_2", payload=payload
    )
    assert receipt.status == "complete"
    assert receipt.exact_replays == 10
    assert receipt.accepted == 0
    assert receipt.review_queue == 0
    assert conn.execute("SELECT count(*) FROM canonical_records").fetchone()[0] == 10


def test_batch_id_reuse_with_different_bytes_fails_closed(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    payload = jsonl(full_records())
    ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_SAME", payload=payload
    )
    with pytest.raises(ValueError, match="batch_id_conflict"):
        ingest_jsonl_batch(
            conn,
            source_id="MYC_SRC_ALPHA",
            batch_id="BATCH_SAME",
            payload=payload + b"\n",
        )


def test_stable_id_payload_conflict_is_rejected_not_overwritten(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_SOURCE", payload=jsonl([source()])
    )
    changed = source()
    changed["source_title"] = "Changed assertion"
    receipt = ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_ALPHA",
        batch_id="BATCH_CONFLICT",
        payload=jsonl([changed]),
    )
    assert receipt.status == "rejected"
    assert receipt.rejected == 1
    assert canonical_payload(conn, "source_registry_entry", "MYC_SRC_ALPHA")["source_title"] == (
        "Fixture MYC_SRC_ALPHA"
    )


def test_negative_survey_without_completed_effort_is_rejected(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_SOURCE", payload=jsonl([source()])
    )
    invalid = survey(outcome="negative", completed=False)
    receipt = ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_ALPHA",
        batch_id="BATCH_NEGATIVE",
        payload=jsonl([invalid]),
    )
    assert receipt.status == "rejected"
    assert receipt.rejected == 1
    assert conn.execute(
        "SELECT count(*) FROM canonical_records WHERE record_type='survey_effort'"
    ).fetchone()[0] == 0


def test_observer_count_mismatch_is_semantic_rejection(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_SOURCE", payload=jsonl([source()])
    )
    invalid = survey()
    invalid["observer_count"] = 2
    receipt = ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_ALPHA",
        batch_id="BATCH_OBSERVERS",
        payload=jsonl([invalid]),
    )
    assert receipt.status == "rejected"
    event = conn.execute(
        "SELECT details_json FROM record_events WHERE basis='semantic_or_binding_failure'"
    ).fetchone()
    assert "observer_count_mismatch" in event[0]


def test_exact_site_coordinates_fail_schema_before_canonicalization(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_ALPHA",
        batch_id="BATCH_PRELOAD",
        payload=jsonl([source(), provenance()]),
    )
    invalid = site()
    invalid["location"]["latitude"] = 18.3
    invalid["location"]["longitude"] = -66.0
    receipt = ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_ALPHA",
        batch_id="BATCH_EXACT_COORD",
        payload=jsonl([invalid]),
    )
    assert receipt.status == "rejected"
    assert receipt.rejected == 1


def test_environmental_snapshot_must_bind_to_same_biological_instant(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    records = full_records()
    for index, record in enumerate(records):
        if record["record_type"] == "temporal_match":
            records[index] = temporal("2026-09-06T10:20:00-04:00")
    receipt = ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_ALPHA",
        batch_id="BATCH_TIME_MISMATCH",
        payload=jsonl(records),
    )
    assert receipt.status == "partial"
    assert receipt.rejected == 1
    assert conn.execute(
        "SELECT count(*) FROM canonical_records WHERE record_type='environmental_snapshot'"
    ).fetchone()[0] == 0


def test_cross_source_duplicate_candidate_is_linked_not_merged(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_ALPHA",
        batch_id="BATCH_ALPHA",
        payload=jsonl([source(), provenance(duplicate_key="shared")]),
    )
    second_source = source("MYC_SRC_BRAVO")
    second_prov = provenance(
        source_id="MYC_SRC_BRAVO",
        provenance_id="MYC_PROV_BRAVO",
        source_record_id="record-bravo",
        duplicate_key="shared",
    )
    receipt = ingest_jsonl_batch(
        conn,
        source_id="MYC_SRC_BRAVO",
        batch_id="BATCH_BRAVO",
        payload=jsonl([second_source, second_prov]),
    )
    assert receipt.duplicate_candidates == 1
    assert conn.execute(
        "SELECT count(*) FROM canonical_records WHERE record_type='provenance_record'"
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT count(*) FROM record_events WHERE event_type='duplicate_candidate'"
    ).fetchone()[0] == 1


def test_nonfinite_json_constant_is_rejected(tmp_path):
    conn = initialize_database(tmp_path / "phase1.sqlite")
    ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_SOURCE", payload=jsonl([source()])
    )
    payload = b'{"record_type":"taxonomic_evidence","schema_version":"1.0.0","x":NaN}\n'
    receipt = ingest_jsonl_batch(
        conn, source_id="MYC_SRC_ALPHA", batch_id="BATCH_NAN", payload=payload
    )
    assert receipt.status == "rejected"
    assert receipt.rejected == 1
    assert conn.execute("SELECT count(*) FROM raw_records").fetchone()[0] == 2


def test_training_filter_does_not_promote_needs_review_lifecycle_record():
    assert training_candidate_only(observation()) is False
    assert training_candidate_only(provenance()) is True
