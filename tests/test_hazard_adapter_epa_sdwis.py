from aguayluz.hazard_adapters.epa_sdwis import (
    canonical_event_id,
    is_tier1_microbial_health_violation,
    normalize,
    stable_record_id,
)
from aguayluz.hazard_plane import RecordKind, RecordStatus


def _row(**overrides):
    row = {
        "pwsid": "PR0002000",
        "violation_id": "9100777",
        "violation_code": "1A",
        "violation_category_code": "MCL",
        "contaminant_code": "3100",
        "is_health_based_ind": "Y",
        "public_notification_tier": "1",
        "rule_group_code": "100",
        "compliance_status_code": "O",
        "compl_per_begin_date": "2024-09-15 00:00:00",
        "compl_per_end_date": "2024-09-30 00:00:00",
    }
    row.update(overrides)
    return row


def test_tier1_microbial_violation_is_event_not_advisory():
    row = _row()
    record = normalize(
        row,
        "EPA_SDWIS:VIOLATION:manifest-1",
        geo_rows=[{"pwsid": "PR0002000", "county_served": "Bayamon Municipio"}],
        municipality_name="Bayamón",
        geography_manifestation_ids=["EPA_SDWIS:GEOGRAPHIC_AREA:manifest-1"],
    )

    assert is_tier1_microbial_health_violation(row) is True
    assert record.record_kind == RecordKind.EVENT
    assert record.hazard_type == "SDWA_TIER1_MICROBIAL_HEALTH_VIOLATION"
    assert record.raw_attributes["advisory_issued"] is False
    assert "NOT_PROOF" in record.raw_attributes["advisory_semantics"]
    assert record.water_system_id == "PR0002000"
    assert record.raw_attributes["municipality_name"] == "Bayamón"


def test_non_microbial_tier1_does_not_become_microbe_signal():
    row = _row(rule_group_code="210")
    record = normalize(row, "manifest-1")

    assert is_tier1_microbial_health_violation(row) is False
    assert record.hazard_type == "SDWA_HEALTH_BASED_VIOLATION"
    assert record.raw_attributes["advisory_issued"] is False


def test_resolved_violation_maps_to_terminated():
    record = normalize(
        _row(compliance_status_code="R"),
        "manifest-1",
    )
    assert record.status == RecordStatus.TERMINATED


def test_missing_compliance_state_is_unresolved_not_active():
    record = normalize(
        _row(compliance_status_code="", violation_status=""),
        "manifest-1",
    )
    assert record.status == RecordStatus.UNRESOLVED


def test_revision_changes_record_identity_but_not_event_identity():
    old = _row(compliance_status_code="O")
    revised = _row(compliance_status_code="R")

    assert canonical_event_id(old) == canonical_event_id(revised)
    assert stable_record_id(old) != stable_record_id(revised)

    old_record = normalize(old, "manifest-old")
    revised_record = normalize(
        revised,
        "manifest-new",
        supersedes_record_id=old_record.record_id,
    )
    assert revised_record.supersedes_record_id == old_record.record_id


def test_missing_authoritative_identifiers_fail_closed():
    try:
        canonical_event_id(_row(violation_id=""))
    except ValueError as exc:
        assert "pwsid and violation_id" in str(exc)
    else:
        raise AssertionError("missing violation_id should fail closed")
