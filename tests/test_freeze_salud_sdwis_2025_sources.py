from scripts.freeze_salud_sdwis_2025_sources import SALUD, classify_pr_row


def _row(**overrides):
    row = {
        "PWSID": "PR0000001",
        "VIOLATION_ID": "V-1",
        "NON_COMPL_PER_BEGIN_DATE": "2025-01-01",
        "NON_COMPL_PER_END_DATE": "2025-12-31",
    }
    row.update(overrides)
    return row


def test_salud_2025_source_family_includes_public_notice_report_and_annexes():
    assert set(SALUD) == {"10746", "10747", "10748"}


def test_pr_row_classification_preserves_open_ended_violation_overlap():
    disposition, reason = classify_pr_row(
        _row(NON_COMPL_PER_END_DATE=""),
        2025,
    )
    assert disposition == "RETAINED"
    assert reason == "PR_2025_OVERLAP"


def test_pr_row_classification_keeps_missing_period_unresolved():
    assert classify_pr_row(
        _row(NON_COMPL_PER_BEGIN_DATE="", NON_COMPL_PER_END_DATE=""),
        2025,
    ) == ("UNRESOLVED", "NONCOMPLIANCE_PERIOD_MISSING")


def test_non_pr_row_is_excluded_before_period_adjudication():
    assert classify_pr_row(
        _row(
            PWSID="NY0000001",
            NON_COMPL_PER_BEGIN_DATE="",
            NON_COMPL_PER_END_DATE="",
        ),
        2025,
    ) == ("EXCLUDED", "NON_PUERTO_RICO_PWSID")


def test_enforcement_only_row_is_not_treated_as_unidentified_violation():
    assert classify_pr_row(
        _row(VIOLATION_ID="", ENFORCEMENT_ID="E-100"),
        2025,
    ) == ("EXCLUDED", "ENFORCEMENT_ONLY_NO_VIOLATION_ID")


def test_export_end_sentinel_is_open_only_for_unresolved_status():
    assert classify_pr_row(
        _row(
            NON_COMPL_PER_BEGIN_DATE="2024-01-01",
            NON_COMPL_PER_END_DATE="--->",
            VIOLATION_STATUS="Unaddressed",
        ),
        2025,
    ) == ("RETAINED", "PR_2025_OVERLAP")

    assert classify_pr_row(
        _row(
            NON_COMPL_PER_BEGIN_DATE="2024-01-01",
            NON_COMPL_PER_END_DATE="--->",
            VIOLATION_STATUS="Resolved",
        ),
        2025,
    ) == ("UNRESOLVED", "INVALID_END_DATE")


def test_open_end_sentinel_does_not_backdate_a_2026_violation_into_2025():
    assert classify_pr_row(
        _row(
            NON_COMPL_PER_BEGIN_DATE="2026-01-01",
            NON_COMPL_PER_END_DATE="--->",
            VIOLATION_STATUS="Addressed",
        ),
        2025,
    ) == ("EXCLUDED", "NO_2025_OVERLAP")
