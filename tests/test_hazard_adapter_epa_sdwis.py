from aguayluz.hazard_adapters.epa_sdwis import (
    CONSUMER_ACTION_UNVERIFIED,
    canonical_event_id,
    normalize,
    stable_record_id,
)
from aguayluz.hazard_plane import HazardFamily, RecordKind, RecordStatus


def _row(**overrides):
    row = {
        "pwsid": "PR0002000",
        "violation_id": "9100777",
        "violation_code": "21",
        "violation_category_code": "MCL",
        "rule_group_code": "100",
        "contaminant_code": "3100",
        "is_health_based_ind": "Y",
        "public_notification_tier": "1",
        "compliance_status_code": "O",
        "compl_per_begin_date": "2026-09-15 00:00:00",
        "compl_per_end_date": "2026-09-30 00:00:00",
        "population_served_count": "1000",
    }
    row.update(overrides)
    return row


def test_tier1_microbial_violation_is_observation_not_boil_water_advisory():
    record = normalize(_row(), "manifest-sdwis-1")

    assert record.family == HazardFamily.WATER_HEALTH
    assert record.record_kind == RecordKind.OBSERVATION
    assert record.hazard_type == "DRINKING_WATER_HEALTH_BASED_VIOLATION"
    assert record.status == RecordStatus.ACTIVE
    assert record.raw_attributes["public_notification_tier"] == "1"
    assert record.raw_attributes["tier1_requires_immediate_public_notice"] is True
    assert record.raw_attributes["consumer_action"] == CONSUMER_ACTION_UNVERIFIED
    assert record.raw_attributes["boil_water_inferred"] is False


def test_pwsid_is_preserved_without_inventing_federation_water_system_binding():
    record = normalize(_row(), "manifest-sdwis-1")

    assert record.water_system_id is None
    assert record.municipality_id is None
    assert record.raw_attributes["pwsid"] == "PR0002000"
    assert record.geography_basis == "EPA_SDWIS_PWSID_STABLE_ID_UNBOUND_TO_FEDERATION_WATER_SYSTEM"
    assert record.geometry_precision == "NONE_UNLESS_INDEPENDENTLY_BOUND"


def test_returned_to_compliance_is_terminated_observation():
    record = normalize(_row(compliance_status_code="R"), "manifest-sdwis-1")
    assert record.status == RecordStatus.TERMINATED


def test_changed_source_content_keeps_event_identity_but_changes_revision_identity():
    row = _row()
    revised = {**row, "compliance_status_code": "R"}

    assert canonical_event_id(row) == canonical_event_id(revised)
    assert stable_record_id(row) != stable_record_id(revised)
