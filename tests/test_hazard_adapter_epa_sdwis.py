import json
from pathlib import Path

from aguayluz.hazard_adapters.epa_sdwis import (
    canonical_event_id,
    normalize,
    stable_record_id,
)
from aguayluz.hazard_plane import HazardFamily, RecordKind, RecordStatus

ROOT = Path(__file__).resolve().parents[1]
ROWS = json.loads((ROOT / "tests" / "fixtures" / "sdwis_violations_sample.json").read_text())
BY_ID = {row["violation_id"]: row for row in ROWS}


def test_identity_uses_authoritative_pwsid_and_violation_id():
    row = BY_ID["9100777"]
    assert canonical_event_id(row) == "EPA_SDWIS:PR0002000:9100777"
    assert stable_record_id(row).startswith("EPA_SDWIS:PR0002000:9100777:REV:")


def test_tier1_microbial_violation_is_event_not_advisory():
    row = BY_ID["9100777"]
    record = normalize(row, "EPA_SDWIS:manifestation:test")

    assert record.family == HazardFamily.WATER_HEALTH
    assert record.record_kind == RecordKind.EVENT
    assert record.hazard_type == "SDWA_MICROBIAL_HEALTH_BASED_VIOLATION"
    assert record.status == RecordStatus.ACTIVE
    assert record.water_system_id == "PR0002000"
    assert record.municipality_id is None
    assert record.facility_id is None
    assert record.raw_attributes["boil_water_advisory_evidence"] == (
        "NOT_ESTABLISHED_BY_SDWIS_VIOLATION_ALONE"
    )
    assert record.raw_attributes["exposure_evidence"] == (
        "NOT_ESTABLISHED_BY_SDWIS_VIOLATION_ALONE"
    )


def test_non_microbial_health_violation_stays_health_violation():
    record = normalize(BY_ID["9200888"], "EPA_SDWIS:manifestation:test")
    assert record.hazard_type == "SDWA_HEALTH_BASED_VIOLATION"
    assert record.record_kind == RecordKind.EVENT


def test_monitoring_reporting_violation_is_not_contamination_claim():
    record = normalize(BY_ID["7613418"], "EPA_SDWIS:manifestation:test")
    assert record.hazard_type == "SDWA_MONITORING_REPORTING_VIOLATION"
    assert record.status == RecordStatus.TERMINATED
    assert record.raw_attributes["exposure_evidence"] == (
        "NOT_ESTABLISHED_BY_SDWIS_VIOLATION_ALONE"
    )


def test_material_source_change_creates_revision_not_new_event():
    original = dict(BY_ID["9001234"])
    revised = dict(original)
    revised["compliance_status_code"] = "R"

    first = normalize(original, "EPA_SDWIS:manifestation:one")
    second = normalize(
        revised,
        "EPA_SDWIS:manifestation:two",
        supersedes_record_id=first.record_id,
    )

    assert first.canonical_event_id == second.canonical_event_id
    assert first.record_id != second.record_id
    assert second.supersedes_record_id == first.record_id
    assert second.status == RecordStatus.TERMINATED


def test_identity_requires_both_authoritative_keys():
    bad = dict(BY_ID["9001234"])
    bad["violation_id"] = None

    try:
        canonical_event_id(bad)
    except ValueError as exc:
        assert "pwsid and violation_id" in str(exc)
    else:
        raise AssertionError("missing violation_id must fail canonical identity")
