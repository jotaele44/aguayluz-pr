from __future__ import annotations

import pytest

from aguayluz.environmental_exposure import (
    derive_entity_id,
    derive_relationship_id,
    integrity_report,
    validate_relationship,
)


def edge(**overrides):
    row = {
        "relationship_id": "AYL_EDGE_TEST",
        "subject_id": "SOURCE",
        "predicate": "POTENTIALLY_AFFECTS",
        "object_id": "WELL",
        "causal_state": "DISCOVERY_CANDIDATE",
        "evidence_classes": ["PROXIMITY_ONLY"],
        "geometry_relation": "NEAR",
        "valid_from": None,
        "valid_until": None,
        "observed_at": None,
        "asserted_at": "2026-08-21T15:15:00Z",
        "source_record_ids": ["SRC-1"],
        "supporting_observation_ids": [],
        "supporting_geometry_ids": [],
        "contradictions": [],
        "falsification_condition": "Hydrogeology excludes connection.",
        "adjudication_state": "CANDIDATE_NOT_IDENTITY",
    }
    row.update(overrides)
    return row


def test_ids_are_deterministic_and_authority_bound():
    assert derive_entity_id("LUST_SITE", "EPA", "X") == derive_entity_id("LUST_SITE", "EPA", "X")
    assert derive_entity_id("LUST_SITE", "EPA", "X") != derive_entity_id("LUST_SITE", "DRNA", "X")
    assert derive_relationship_id("A", "POTENTIALLY_AFFECTS", "B") == derive_relationship_id(
        "A", "POTENTIALLY_AFFECTS", "B"
    )


def test_proximity_only_candidate_is_allowed():
    validate_relationship(edge())


def test_proximity_only_causal_promotion_fails_closed():
    with pytest.raises(ValueError, match="causal promotion"):
        validate_relationship(edge(
            predicate="AFFECTS",
            causal_state="ATTRIBUTION_SUPPORTED",
        ))


def test_authoritative_attribution_rejects_open_contradictions():
    with pytest.raises(ValueError, match="open contradictions"):
        validate_relationship(edge(
            predicate="ATTRIBUTED_TO",
            causal_state="AUTHORITATIVELY_ATTRIBUTED",
            evidence_classes=["AUTHORITATIVE_BINDING"],
            contradictions=["CONTRA-1"],
        ))


def test_integrity_reports_orphans_and_closes_arithmetic():
    report = integrity_report(
        entity_ids=["SOURCE", "WELL"],
        observation_ids=[],
        geometry_ids=[],
        relationships=[edge()],
    )
    assert report["arithmetic_closes"] is True
    assert report["relationship_count"] == report["state_count_sum"]
    assert report["certification_state"] == "PASS"

    bad = integrity_report(
        entity_ids=["SOURCE"],
        observation_ids=[],
        geometry_ids=[],
        relationships=[edge()],
    )
    assert bad["certification_state"] == "FAIL"
    assert any("orphan object_id" in item for item in bad["errors"])


def test_integrity_accepts_existing_utility_asset_as_graph_endpoint():
    report = integrity_report(
        entity_ids=["SOURCE"],
        external_entity_ids=["UTILITY_1"],
        observation_ids=[],
        geometry_ids=[],
        relationships=[edge(object_id="UTILITY_1")],
    )
    assert report["certification_state"] == "PASS"
    assert report["external_entity_count"] == 1
