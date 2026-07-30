import pytest
from server.backend.water_disruption import WaterIncidentService


def candidate(candidate_id="WDC-PROMOTE-1", dedup_key="WDK-PROMOTE-1"):
    return {
        "schema_version": "centinelas.water-candidate/v0.1",
        "candidate_id": candidate_id,
        "truth_state": "candidate",
        "event_type": "main_break",
        "municipalities": ["Caguas"],
        "asset_hint": "main-1",
        "dedup_key": dedup_key,
        "evidence_ids": ["EVD-1"],
        "source_ids": ["prasa"],
        "confidence": {"overall": 1.0},
        "shadow_mode": True,
    }


def test_unverified_then_authoritative_confirmation_promotes_append_only(tmp_path):
    service = WaterIncidentService(tmp_path)
    item = candidate()
    unverified = service.validation_policy(item)
    first = service.validate(item, unverified, "shadow-reviewer", "VAL-1")
    incident_id = service.store.read("incidents")[0]["incident_id"]
    original = dict(service.store.read("incidents")[0])

    confirmed = service.validation_policy(item, authoritative_scope_match=True)
    second = service.validate(item, confirmed, "authority-reviewer", "VAL-2")
    current = service.current_incident(incident_id)

    assert first["decision"] == "unverified"
    assert second["decision"] == "confirmed"
    assert current["truth_state"] == "confirmed"
    assert current["lifecycle_state"] == "confirmed"
    assert len(service.store.read("incidents")) == 1
    assert service.store.read("incidents")[0] == original
    assert [row["to_truth_state"] for row in current["truth_events"]] == ["unverified", "confirmed"]
    assert current["truth_events"][-1]["validation_id"] == second["validation_id"]


def test_corroborated_then_reviewer_confirmation_promotes(tmp_path):
    service = WaterIncidentService(tmp_path)
    item = candidate()
    corroborated = service.validation_policy(item, independent_source_count=2)
    service.validate(item, corroborated, "reviewer", "VAL-1")
    confirmed = service.validation_policy(item, independent_source_count=2, reviewer_approved=True)
    service.validate(item, confirmed, "reviewer", "VAL-2")
    incident_id = service.store.read("incidents")[0]["incident_id"]
    current = service.current_incident(incident_id)
    assert current["truth_state"] == "confirmed"
    assert current["lifecycle_state"] == "confirmed"


def test_duplicate_confirmation_replay_is_idempotent(tmp_path):
    service = WaterIncidentService(tmp_path)
    item = candidate()
    decision = service.validation_policy(item, authoritative_scope_match=True)
    first = service.validate(item, decision, "reviewer", "VAL-1")
    second = service.validate(item, decision, "reviewer", "VAL-1")
    assert first == second
    assert len(service.store.read("validation_events")) == 1
    assert len(service.store.read("incident_truth_events")) == 1


def test_conflicting_validation_key_fails_closed(tmp_path):
    service = WaterIncidentService(tmp_path)
    item = candidate()
    service.validate(item, service.validation_policy(item), "reviewer", "VAL-1")
    with pytest.raises(ValueError, match="validation_idempotency_conflict"):
        service.validate(
            item,
            service.validation_policy(item, authoritative_scope_match=True),
            "reviewer",
            "VAL-1",
        )


def test_weaker_validation_cannot_downgrade_confirmed_incident(tmp_path):
    service = WaterIncidentService(tmp_path)
    item = candidate()
    confirmed = service.validation_policy(item, authoritative_scope_match=True)
    service.validate(item, confirmed, "reviewer", "VAL-1")
    weaker = service.validation_policy(item)
    service.validate(item, weaker, "reviewer", "VAL-2")
    incident_id = service.store.read("incidents")[0]["incident_id"]
    current = service.current_incident(incident_id)
    assert current["truth_state"] == "confirmed"
    assert [row["to_truth_state"] for row in current["truth_events"]] == ["confirmed"]


def test_retraction_after_promotion_preserves_original_records(tmp_path):
    service = WaterIncidentService(tmp_path)
    item = candidate()
    service.validate(item, service.validation_policy(item), "reviewer", "VAL-1")
    service.validate(
        item,
        service.validation_policy(item, authoritative_scope_match=True),
        "reviewer",
        "VAL-2",
    )
    original_incident = dict(service.store.read("incidents")[0])
    original_validation_count = len(service.store.read("validation_events"))

    event = service.retract(item["candidate_id"], "source correction", "RET-1")
    incident_id = original_incident["incident_id"]
    current = service.current_incident(incident_id)

    assert event["destructive"] is False
    assert current["truth_state"] == "retracted"
    assert current["lifecycle_state"] == "retracted"
    assert service.store.read("incidents")[0] == original_incident
    assert len(service.store.read("validation_events")) == original_validation_count
    assert service.notifications_enabled is False
    assert service.production_promotion_enabled is False
