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


def observation(**overrides):
    row = {"observation_id": "OBS_1", "entity_ids": ["SOURCE"]}
    row.update(overrides)
    return row


def geometry(**overrides):
    row = {"geometry_id": "GEO_1", "entity_id": "SOURCE"}
    row.update(overrides)
    return row


def event(**overrides):
    row = {"event_id": "EVT_1", "entity_ids": ["SOURCE"]}
    row.update(overrides)
    return row


def report(**overrides):
    values = {
        "entity_ids": ["SOURCE", "WELL"],
        "observations": [],
        "geometries": [],
        "events": [],
        "relationships": [edge()],
    }
    values.update(overrides)
    return integrity_report(**values)


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


def test_structural_integrity_pass_is_not_corpus_certification():
    result = report()
    assert result["arithmetic_closes"] is True
    assert result["relationship_count"] == result["state_count_sum"]
    assert result["structural_integrity_state"] == "PASS"
    assert result["corpus_certification_state"] == "OPEN"


def test_integrity_reports_orphan_relationship_endpoint():
    result = report(entity_ids=["SOURCE"])
    assert result["structural_integrity_state"] == "FAIL"
    assert any("orphan object_id" in item for item in result["errors"])


def test_integrity_accepts_existing_utility_asset_as_graph_endpoint():
    result = report(
        entity_ids=["SOURCE"],
        external_entity_ids=["UTILITY_1"],
        relationships=[edge(object_id="UTILITY_1")],
    )
    assert result["structural_integrity_state"] == "PASS"
    assert result["external_entity_count"] == 1


def test_integrity_rejects_orphans_from_observations_geometries_and_events():
    result = report(
        observations=[observation(entity_ids=["MISSING_OBS_ENTITY"])],
        geometries=[geometry(entity_id="MISSING_GEO_ENTITY")],
        events=[event(entity_ids=["MISSING_EVENT_ENTITY"])],
    )
    assert result["structural_integrity_state"] == "FAIL"
    assert any(item == "OBS_1: orphan entity_id MISSING_OBS_ENTITY" for item in result["errors"])
    assert any(item == "GEO_1: orphan entity_id MISSING_GEO_ENTITY" for item in result["errors"])
    assert any(item == "EVT_1: orphan entity_id MISSING_EVENT_ENTITY" for item in result["errors"])


def test_duplicate_ids_and_identity_collision_fail_closed():
    duplicate_edge = edge(relationship_id="AYL_EDGE_TEST")
    result = report(
        entity_ids=["SOURCE", "WELL", "SOURCE"],
        external_entity_ids=["WELL"],
        observations=[observation(), observation()],
        geometries=[geometry(), geometry()],
        events=[event(), event()],
        relationships=[edge(), duplicate_edge],
    )
    assert result["structural_integrity_state"] == "FAIL"
    assert result["duplicate_ids"]["entity_id"] == ["SOURCE"]
    assert result["duplicate_ids"]["observation_id"] == ["OBS_1"]
    assert result["duplicate_ids"]["geometry_id"] == ["GEO_1"]
    assert result["duplicate_ids"]["event_id"] == ["EVT_1"]
    assert result["duplicate_ids"]["relationship_id"] == ["AYL_EDGE_TEST"]
    assert any(item == "environmental/external identity collision: WELL" for item in result["errors"])
