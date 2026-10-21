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
