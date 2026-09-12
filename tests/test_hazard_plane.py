from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from aguayluz.hazard_plane import (
    CaseClass,
    EntityKind,
    EvidenceClass,
    HazardFamily,
    HazardRecord,
    HazardRelationship,
    Manifestation,
    RecordKind,
    RecordStatus,
    RelationshipType,
    current_records,
    integrity_report,
    source_arithmetic,
)

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def record(record_id="evt-1:rev-a", **overrides):
    row = {
        "record_id": record_id,
        "canonical_event_id": "evt-1",
        "record_kind": RecordKind.ADVISORY,
        "family": HazardFamily.WATER_HEALTH,
        "hazard_type": "BEACH_ADVISORY",
        "source_authority": "DRNA",
        "source_record_id": record_id,
        "manifestation_id": "manifest-1",
        "title_raw": "Notificación Monitoria de Playas",
        "status": RecordStatus.ACTIVE,
        "issued_at": NOW,
    }
    row.update(overrides)
    return HazardRecord(**row)


def manifestation(manifestation_id="manifest-1"):
    return Manifestation(
        manifestation_id=manifestation_id,
        source_authority="DRNA",
        source_system="beach-monitoring",
        source_record_id="notice-1",
        source_url="https://example.invalid/notice-1",
        retrieved_at_utc=NOW,
        byte_sha256="0" * 64,
    )


def test_source_arithmetic_fails_closed_on_unexplained_delta():
    assert source_arithmetic(10, 7, 2, 1)["state"] == "PASS"
    result = source_arithmetic(10, 7, 1, 1)
    assert result["state"] == "FAIL"
    assert result["delta"] == 1


def test_revision_selection_uses_whole_latest_row():
    old = record("evt-1:rev-old", status=RecordStatus.SUPERSEDED)
    new = record(
        "evt-1:rev-new",
        supersedes_record_id="evt-1:rev-old",
        title_raw="Revised advisory",
    )
    rows = current_records([old, new])
    assert [row.record_id for row in rows] == ["evt-1:rev-new"]
    assert rows[0].title_raw == "Revised advisory"


def test_cross_event_supersedes_fails_integrity():
    old = record("evt-1:rev-old")
    new = record(
        "evt-2:rev-new",
        canonical_event_id="evt-2",
        supersedes_record_id="evt-1:rev-old",
    )
    result = integrity_report([old, new], [], [manifestation()])
    assert result["state"] == "FAIL"
    assert result["cross_event_supersedes"] == ["evt-2:rev-new"]


def test_human_disease_requires_case_semantics():
    with pytest.raises(ValidationError):
        record(
            family=HazardFamily.HUMAN_INFECTIOUS_DISEASE,
            hazard_type="DENGUE",
        )
    disease = record(
        family=HazardFamily.HUMAN_INFECTIOUS_DISEASE,
        hazard_type="DENGUE",
        case_class=CaseClass.CONFIRMED,
        case_definition_version="PRDOH-2026-W35",
        confirmed_cases=4,
    )
    assert disease.confirmed_cases == 4


def test_proximity_cannot_be_promoted_to_causal_confirmation():
    with pytest.raises(ValidationError):
        HazardRelationship(
            relationship_id="rel-1",
            subject_id="evt-1:rev-a",
            predicate=RelationshipType.CAUSALLY_CONFIRMED,
            object_id="evt-2:rev-a",
            evidence_class=EvidenceClass.PROXIMITY,
            source_manifestation_ids=["manifest-1"],
        )


def test_statistical_association_requires_method_and_sample_size():
    with pytest.raises(ValidationError):
        HazardRelationship(
            relationship_id="rel-1",
            subject_id="evt-1:rev-a",
            predicate=RelationshipType.STATISTICAL_ASSOCIATION,
            object_id="evt-2:rev-a",
            evidence_class=EvidenceClass.AUTHORITATIVE_BINDING,
            source_manifestation_ids=["manifest-1"],
        )


def test_integrity_detects_missing_manifestation_and_dangling_hazard_edge():
    edge = HazardRelationship(
        relationship_id="rel-1",
        subject_id="evt-1:rev-a",
        predicate=RelationshipType.SAME_WATERSHED,
        object_id="missing-record",
        evidence_class=EvidenceClass.CERTIFIED_GEOMETRY,
        source_manifestation_ids=["missing-manifest"],
    )
    result = integrity_report([record()], [edge], [manifestation()])
    assert result["state"] == "FAIL"
    assert result["dangling_relationships"] == ["rel-1"]
    assert result["missing_manifestations"] == ["missing-manifest"]


def test_external_federation_entity_is_not_misclassified_as_dangling_hazard_record():
    edge = HazardRelationship(
        relationship_id="rel-water-system",
        subject_id="evt-1:rev-a",
        predicate=RelationshipType.SAME_WATER_SYSTEM,
        object_id="AYL_WATER_SYSTEM_123",
        object_kind=EntityKind.WATER_SYSTEM,
        evidence_class=EvidenceClass.AUTHORITATIVE_BINDING,
        source_manifestation_ids=["manifest-1"],
    )
    result = integrity_report([record()], [edge], [manifestation()])
    assert result["state"] == "PASS"
    assert result["dangling_relationships"] == []


def test_duplicate_relationship_and_manifestation_ids_fail_closed():
    edge = HazardRelationship(
        relationship_id="rel-dup",
        subject_id="evt-1:rev-a",
        predicate=RelationshipType.TEMPORALLY_OVERLAPS,
        object_id="evt-1:rev-a",
        evidence_class=EvidenceClass.AUTHORITATIVE_BINDING,
        source_manifestation_ids=["manifest-1"],
    )
    result = integrity_report(
        [record()],
        [edge, edge.model_copy()],
        [manifestation(), manifestation()],
    )
    assert result["state"] == "FAIL"
    assert result["duplicate_relationship_ids"] == ["rel-dup"]
    assert result["duplicate_manifestation_ids"] == ["manifest-1"]


def test_temporal_end_cannot_precede_start():
    with pytest.raises(ValidationError):
        record(observed_from=NOW, observed_to=datetime(2026, 9, 4, tzinfo=timezone.utc))
