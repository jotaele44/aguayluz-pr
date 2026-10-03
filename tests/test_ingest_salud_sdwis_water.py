import csv
from pathlib import Path

import pytest
from scripts.ingest_salud_sdwis_water import classify_sdwis_row, run

from aguayluz.hazard_plane import HazardRecord, current_records


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "SUBMISSIONYEARQUARTER",
        "PWSID",
        "PWS_NAME",
        "VIOLATION_ID",
        "FACILITY_ID",
        "NON_COMPL_PER_BEGIN_DATE",
        "NON_COMPL_PER_END_DATE",
        "VIOLATION_CATEGORY_CODE",
        "VIOLATION_NAME",
        "IS_HEALTH_BASED_IND",
        "VIOLATION_STATUS",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _base(**overrides):
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
    }
    row.update(overrides)
    return row


def test_sdwis_row_classification_is_bounded_by_pwsid_and_calendar_overlap():
    assert classify_sdwis_row(_base(), 2025)[0] == "RETAINED"
    assert classify_sdwis_row(_base(PWSID="NY0000001"), 2025) == (
        "EXCLUDED",
        "NON_PUERTO_RICO_PWSID",
    )
    assert classify_sdwis_row(
        _base(
            NON_COMPL_PER_BEGIN_DATE="2024-01-01",
            NON_COMPL_PER_END_DATE="2024-12-31",
        ),
        2025,
    )[0] == "EXCLUDED"
    assert classify_sdwis_row(
        _base(NON_COMPL_PER_BEGIN_DATE="", NON_COMPL_PER_END_DATE=""),
        2025,
    ) == ("UNRESOLVED", "NONCOMPLIANCE_PERIOD_MISSING")


def test_blocked_salud_locators_and_sdwis_source_arithmetic_are_preserved(tmp_path):
    csv_path = tmp_path / "sdwis.csv"
    _write_csv(
        csv_path,
        [
            _base(),
            _base(
                VIOLATION_ID="V-101",
                NON_COMPL_PER_BEGIN_DATE="2024-01-01",
                NON_COMPL_PER_END_DATE="2024-12-31",
            ),
            _base(PWSID="NY0000001", VIOLATION_ID="V-102"),
            _base(
                VIOLATION_ID="V-103",
                NON_COMPL_PER_BEGIN_DATE="",
                NON_COMPL_PER_END_DATE="",
            ),
        ],
    )

    receipt = run(
        year=2025,
        output_root=tmp_path / "out",
        sdwis_violations=csv_path,
        sdwis_source_url="https://example.invalid/official-sdwis.csv",
    )

    assert receipt["salud_artifact_arithmetic"] == {
        "source": 3,
        "frozen": 0,
        "blocked": 2,
        "present_unfrozen": 1,
        "accounted": 3,
        "delta": 0,
        "state": "PASS",
    }
    by_id = {row["source_record_id"]: row for row in receipt["salud_artifacts"]}
    assert by_id["10747"]["status"] == "BLOCKED_ACQUISITION"
    assert by_id["10748"]["status"] == "BLOCKED_ACQUISITION"
    assert by_id["10747"]["byte_sha256"] is None
    assert receipt["sdwis_source_arithmetic"] == {
        "source": 4,
        "retained": 1,
        "excluded": 2,
        "unresolved": 1,
        "accounted": 4,
        "delta": 0,
        "state": "PASS",
    }
    assert receipt["certification_state"] == "OPEN"


def test_all_three_salud_artifacts_can_move_to_frozen_without_schema_change(tmp_path):
    public_notice = tmp_path / "10746.pdf"
    report = tmp_path / "10747.pdf"
    annex = tmp_path / "10748.pdf"
    public_notice.write_bytes(b"%PDF-fixture-public-notice")
    report.write_bytes(b"%PDF-fixture-report")
    annex.write_bytes(b"%PDF-fixture-annex")
    csv_path = tmp_path / "sdwis.csv"
    _write_csv(csv_path, [_base()])

    receipt = run(
        year=2025,
        output_root=tmp_path / "out",
        salud_public_notice=public_notice,
        salud_report=report,
        salud_annex=annex,
        sdwis_violations=csv_path,
        sdwis_source_url="https://example.invalid/official-sdwis.csv",
        require_zero_unresolved=True,
    )

    assert receipt["salud_artifact_arithmetic"]["frozen"] == 3
    assert receipt["salud_artifact_arithmetic"]["blocked"] == 0
    assert all(row["byte_sha256"] for row in receipt["salud_artifacts"])
    assert receipt["certification_state"] == "BOUNDED_INPUT_PASS"


def test_changed_sdwis_row_supersedes_only_same_canonical_violation(tmp_path):
    output = tmp_path / "out"
    csv_path = tmp_path / "sdwis.csv"
    _write_csv(csv_path, [_base(VIOLATION_STATUS="Unaddressed")])
    run(
        year=2025,
        output_root=output,
        sdwis_violations=csv_path,
        sdwis_source_url="https://example.invalid/official-sdwis-v1.csv",
    )

    _write_csv(csv_path, [_base(VIOLATION_STATUS="Resolved")])
    run(
        year=2025,
        output_root=output,
        sdwis_violations=csv_path,
        sdwis_source_url="https://example.invalid/official-sdwis-v2.csv",
    )

    rows = [
        HazardRecord.model_validate_json(line)
        for line in (output / "hazard_records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2
    assert len({row.canonical_event_id for row in rows}) == 1
    current = current_records(rows)
    assert len(current) == 1
    assert current[0].status.value == "INACTIVE"
    assert current[0].supersedes_record_id is not None


def test_sdwis_source_url_is_required_for_traceability(tmp_path):
    csv_path = tmp_path / "sdwis.csv"
    _write_csv(csv_path, [_base()])

    with pytest.raises(ValueError, match="exact HTTPS source locator"):
        run(
            year=2025,
            output_root=tmp_path / "out",
            sdwis_violations=csv_path,
        )
