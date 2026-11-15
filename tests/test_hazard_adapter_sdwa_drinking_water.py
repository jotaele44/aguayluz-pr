from aguayluz.hazard_adapters.sdwa_drinking_water import (
    canonical_event_id,
    normalize,
    stable_record_id,
)
from aguayluz.hazard_plane import HazardFamily, RecordKind, RecordStatus


def _row(**overrides):
    row = {
        "SUBMISSIONYEARQUARTER": "2026Q3",
        "PWSID": "PR0000001",
        "PWS_NAME": "Fixture Water System",
        "VIOLATION_ID": "V-100",
        "FACILITY_ID": "F-20",
        "NON_COMPL_PER_BEGIN_DATE": "2025-02-01",
        "NON_COMPL_PER_END_DATE": "2025-03-01",
        "VIOLATION_CATEGORY_CODE": "MCL",
        "VIOLATION_NAME": "MCL violation",
        "IS_HEALTH_BASED_IND": "Y",
        "VIOLATION_STATUS": "Unaddressed",
        "CONTAMINANT_CODE": "3000",
        "VIOL_MEASURE": "2.0",
        "UNIT_OF_MEASURE": "mg/L",
        "FEDERAL_MCL": "1.0",
        "STATE_MCL": "1.0",
    }
    row.update(overrides)
    return row


def test_mcl_violation_uses_authoritative_sdwis_identity_without_geometry_inference():
    record = normalize(_row(), "manifest-sdwis-1")

    assert record.family == HazardFamily.WATER_HEALTH
    assert record.record_kind == RecordKind.EVENT
    assert record.hazard_type == "DRINKING_WATER_MCL_VIOLATION"
    assert record.status == RecordStatus.ACTIVE
    assert record.water_system_id == "EPA_PWSID:PR0000001"
    assert record.facility_id == "EPA_PWSID:PR0000001:FACILITY:F-20"
    assert record.geography_basis == "EPA_SDWIS_STABLE_ID"
    assert record.geometry_precision == "NONE_UNLESS_INDEPENDENTLY_BOUND"


def test_monitoring_failure_is_not_promoted_to_contaminant_exceedance():
    record = normalize(
        _row(
            VIOLATION_CATEGORY_CODE="MON",
            VIOLATION_NAME="Monitoring and Reporting",
            IS_HEALTH_BASED_IND="N",
            VIOL_MEASURE="",
            FEDERAL_MCL="",
            STATE_MCL="",
        ),
        "manifest-sdwis-2",
    )

    assert record.hazard_type == "DRINKING_WATER_MONITORING_REPORTING_VIOLATION"
    assert "exposure" in record.raw_attributes["semantic_guardrail"].lower()
    assert record.raw_attributes["violation_measure"] is None


def test_same_violation_keeps_event_identity_but_changed_row_gets_new_revision_identity():
    original = _row(VIOLATION_STATUS="Unaddressed")
    revised = _row(VIOLATION_STATUS="Resolved")

    assert canonical_event_id(original) == canonical_event_id(revised)
    assert stable_record_id(original) != stable_record_id(revised)


def test_unresolved_status_does_not_match_resolved_by_substring():
    record = normalize(_row(VIOLATION_STATUS="Unresolved"), "manifest-sdwis-3")
    assert record.status == RecordStatus.ACTIVE
