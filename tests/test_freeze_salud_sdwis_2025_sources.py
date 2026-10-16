from scripts.freeze_salud_sdwis_2025_sources import classify_pr_row


def _row(**overrides):
    row = {
        "PWSID": "PR0000001",
        "VIOLATION_ID": "V-1",
        "ENFORCEMENT_ID": "",
        "NON_COMPL_PER_BEGIN_DATE": "01/01/2025",
        "NON_COMPL_PER_END_DATE": "12/31/2025",
        "VIOLATION_CODE": "01",
        "VIOLATION_CATEGORY_CODE": "MCL",
        "VIOLATION_STATUS": "Unaddressed",
    }
    row.update(overrides)
    return row


def test_enforcement_only_row_is_excluded_from_violation_denominator():
    disposition, reason = classify_pr_row(
        _row(
            VIOLATION_ID="",
            ENFORCEMENT_ID="8025042",
            NON_COMPL_PER_BEGIN_DATE="",
            NON_COMPL_PER_END_DATE="",
            VIOLATION_CODE="",
            VIOLATION_CATEGORY_CODE="",
            VIOLATION_STATUS="",
        ),
        2025,
    )
    assert (disposition, reason) == (
        "EXCLUDED",
        "ENFORCEMENT_ONLY_NO_VIOLATION_ID",
    )


def test_missing_violation_id_with_violation_payload_remains_unresolved():
    disposition, reason = classify_pr_row(
        _row(VIOLATION_ID="", ENFORCEMENT_ID="8025042"),
        2025,
    )
    assert (disposition, reason) == ("UNRESOLVED", "MISSING_VIOLATION_ID")


def test_open_unaddressed_sentinel_overlaps_target_year():
    disposition, reason = classify_pr_row(
        _row(
            NON_COMPL_PER_BEGIN_DATE="10/17/2024",
            NON_COMPL_PER_END_DATE="--->",
            VIOLATION_STATUS="Unaddressed",
        ),
        2025,
    )
    assert (disposition, reason) == (
        "RETAINED",
        "PR_2025_OVERLAP_OPEN_UNADDRESSED",
    )


def test_open_unaddressed_sentinel_starting_after_target_year_is_excluded():
    disposition, reason = classify_pr_row(
        _row(
            NON_COMPL_PER_BEGIN_DATE="01/01/2026",
            NON_COMPL_PER_END_DATE="--->",
            VIOLATION_STATUS="Unaddressed",
        ),
        2025,
    )
    assert (disposition, reason) == (
        "EXCLUDED",
        "OPEN_UNADDRESSED_START_AFTER_TARGET_YEAR",
    )


def test_addressed_sentinel_end_date_remains_unresolved():
    disposition, reason = classify_pr_row(
        _row(
            NON_COMPL_PER_BEGIN_DATE="01/01/2007",
            NON_COMPL_PER_END_DATE="--->",
            VIOLATION_STATUS="Addressed",
        ),
        2025,
    )
    assert (disposition, reason) == ("UNRESOLVED", "MISSING_END_DATE_ADDRESSED")


def test_non_pr_row_is_excluded_before_violation_adjudication():
    disposition, reason = classify_pr_row(
        _row(PWSID="NY0000001", VIOLATION_ID=""),
        2025,
    )
    assert (disposition, reason) == ("EXCLUDED", "NON_PUERTO_RICO_PWSID")
