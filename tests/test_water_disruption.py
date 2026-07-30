import pytest

from server.backend.water_disruption import WaterIncidentService


def candidate(candidate_id="WDC-1", dedup_key="WDK-1", confidence=1.0):
    return {
        "schema_version": "centinelas.water-candidate/v0.1",
        "candidate_id": candidate_id,
        "truth_state": "candidate",
        "event_type": "service_outage",
        "municipalities": ["Caguas"],
        "asset_hint": "main-1",
        "dedup_key": dedup_key,
        "evidence_ids": ["EVD-1"],
        "source_ids": ["prasa"],
        "confidence": {"overall": confidence},
        "shadow_mode": True,
    }


def test_intake_is_idempotent_and_rejects_changed_payload(tmp_path):
    service = WaterIncidentService(tmp_path)
    first = service.intake({"payload": candidate()}, "KEY-1")
    second = service.intake({"payload": candidate()}, "KEY-1")
    assert first["receipt_id"] == second["receipt_id"]
    assert second["replayed"] is True
    changed = candidate()
    changed["event_type"] = "main_break"
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        service.intake({"payload": changed}, "KEY-1")


def test_high_confidence_alone_never_confirms(tmp_path):
    service = WaterIncidentService(tmp_path)
    decision = service.validation_policy(candidate(confidence=1.0))
    assert decision["decision"] == "unverified"
    assert decision["confidence_ignored_for_confirmation"] is True


def test_confirmation_requires_authority_or_two_sources_and_review(tmp_path):
    service = WaterIncidentService(tmp_path)
    official = service.validation_policy(candidate(), authoritative_scope_match=True)
    assert official["decision"] == "confirmed"
    two_no_review = service.validation_policy(candidate(), independent_source_count=2)
    assert two_no_review["decision"] == "corroborated"
    two_review = service.validation_policy(candidate(), independent_source_count=2, reviewer_approved=True)
    assert two_review["decision"] == "confirmed"


def test_private_plumbing_fails_domain_gate(tmp_path):
    service = WaterIncidentService(tmp_path)
    decision = service.validation_policy(candidate(), public_infrastructure=False, authoritative_scope_match=True)
    assert decision["decision"] == "rejected"
    assert "not_public_infrastructure" in decision["blockers"]


def test_incident_dedup_and_invalid_transition(tmp_path):
    service = WaterIncidentService(tmp_path)
    item = candidate()
    decision = service.validation_policy(item, authoritative_scope_match=True)
    service.validate(item, decision, "reviewer", "VAL-1")
    first = service.resolve_incident(item, decision)
    second = service.resolve_incident(item, decision)
    assert first["incident_id"] == second["incident_id"]
    with pytest.raises(ValueError, match="invalid_transition"):
        service.transition(first["incident_id"], "closed", "skip", "TR-1")


def test_restoration_reopen_and_retraction_propagate(tmp_path):
    service = WaterIncidentService(tmp_path)
    item = candidate()
    decision = service.validation_policy(item, authoritative_scope_match=True)
    service.validate(item, decision, "reviewer", "VAL-1")
    incident = service.resolve_incident(item, decision)
    service.transition(incident["incident_id"], "restored", "service restored", "TR-1")
    service.transition(incident["incident_id"], "repair_in_progress", "outage recurred", "TR-2")
    assert service.current_incident(incident["incident_id"])["lifecycle_state"] == "repair_in_progress"
    event = service.retract(item["candidate_id"], "source correction", "RET-1")
    assert event["destructive"] is False
    assert service.current_incident(incident["incident_id"])["lifecycle_state"] == "retracted"
    assert service.notifications_enabled is False


def test_merge_and_split_are_append_only(tmp_path):
    service = WaterIncidentService(tmp_path)
    for index in (1, 2):
        item = candidate(f"WDC-{index}", f"WDK-{index}")
        decision = service.validation_policy(item, authoritative_scope_match=True)
        service.validate(item, decision, "reviewer", f"VAL-{index}")
    ids = [row["incident_id"] for row in service.store.read("incidents")]
    merged = service.merge(ids[0], [ids[1]], "same outage", "M-1")
    split = service.split(ids[0], ["WDK-A", "WDK-B"], "distinct assets", "S-1")
    assert merged["operation"] == "merge"
    assert split["operation"] == "split"
    assert len(service.store.read("merge_split_events")) == 2
