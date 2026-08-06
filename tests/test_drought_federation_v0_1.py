from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research.drought.federation import (
    DroughtRecord,
    build_nidis_source_document,
    classify_date_text,
    normalize_reported_value,
)

ROOT = Path(__file__).resolve().parents[1]


def test_schema_and_claim_manifest_are_valid_json() -> None:
    schema = json.loads(
        (ROOT / "schemas/drought-federation/v0.1/drought-record.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    manifest = json.loads(
        (ROOT / "research/drought/nidis_2026_07_23_claim_manifest.json").read_text()
    )
    assert len(manifest["claims"]) == 10
    assert len({claim["claim_id"] for claim in manifest["claims"]}) == 10


def test_source_document_is_not_canonical_observation_authority() -> None:
    record = build_nidis_source_document(
        source_sha256="0" * 64,
        retrieved_at="2026-08-06T02:00:00Z",
        claim_ids=["NIDIS_PR_20260723_002", "NIDIS_PR_20260723_001"],
    ).to_dict()
    assert record["kind"] == "source_document"
    assert record["payload"]["canonical_observation_authority"] is False
    assert record["payload"]["claim_ids"] == [
        "NIDIS_PR_20260723_001",
        "NIDIS_PR_20260723_002",
    ]
    assert len(record["content_sha256"]) == 64


def test_record_id_and_hash_are_deterministic() -> None:
    kwargs = {
        "kind": "impact_event",
        "source_id": "NOAA_NIDIS",
        "source_record_id": "claim-008",
        "observed_at": "2026-07-21T17:00:00-04:00",
        "issued_at": "2026-07-23T00:00:00-04:00",
        "retrieved_at": "2026-08-06T02:00:00Z",
        "evidence_tier": "T2",
        "payload": {"impact_type": "wildfire_activity"},
        "quality": {"review_status": "candidate"},
        "uncertainty": {"reported_count_is_approximate": True},
        "lineage": {"claim_id": "NIDIS_PR_20260723_008"},
    }
    first = DroughtRecord(**kwargs).to_dict()
    second = DroughtRecord(**kwargs).to_dict()
    assert first == second


def test_approximate_and_range_values_preserve_uncertainty() -> None:
    approximate = normalize_reported_value(
        value=5,
        unit="percent_reduction",
        qualifier="approximate",
        raw_text="approximately 5%",
    )
    assert approximate["qualifier"] == "approximate"
    rainfall = normalize_reported_value(
        qualifier="range",
        minimum=3,
        maximum=6,
        unit="inch",
        raw_text="3–6 inches",
    )
    assert rainfall["value"] is None
    with pytest.raises(ValueError):
        normalize_reported_value(
            qualifier="range", minimum=6, maximum=3, unit="inch", raw_text="bad range"
        )


def test_source_typo_fails_closed() -> None:
    result = classify_date_text("July 210, 2026")
    assert result["status"] == "source_typo_unresolved"
    assert result["normalized_date"] is None
