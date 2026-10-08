from scripts.freeze_salud_sdwis_2025_sources import classify


def _row(**overrides: str) -> dict[str, str]:
    row = {
        "PWSID": "PR0000001",
        "VIOLATION_ID": "V-1",
        "NON_COMPL_PER_BEGIN_DATE": "2025-01-01",
        "NON_COMPL_PER_END_DATE": "2025-12-31",
    }
    row.update(overrides)
    return row


def test_pr_violation_overlapping_target_year_is_retained() -> None:
    assert classify(_row(), 2025) == ("RETAINED", "PR_2025_OVERLAP")


def test_non_pr_system_is_excluded() -> None:
    assert classify(_row(PWSID="NY0000001"), 2025) == (
        "EXCLUDED",
        "NON_PUERTO_RICO_PWSID",
    )


def test_missing_stable_identity_is_unresolved() -> None:
    assert classify(_row(VIOLATION_ID=""), 2025) == (
        "UNRESOLVED",
        "MISSING_PWSID_OR_VIOLATION_ID",
    )


def test_invalid_date_is_unresolved() -> None:
    assert classify(_row(NON_COMPL_PER_BEGIN_DATE="not-a-date"), 2025) == (
        "UNRESOLVED",
        "INVALID_BEGIN_DATE",
    )


def test_violation_outside_target_year_is_excluded() -> None:
    assert classify(
        _row(
            NON_COMPL_PER_BEGIN_DATE="2024-01-01",
            NON_COMPL_PER_END_DATE="2024-12-31",
        ),
        2025,
    ) == ("EXCLUDED", "NO_2025_OVERLAP")


def test_open_ended_violation_overlapping_target_year_is_retained() -> None:
    assert classify(_row(NON_COMPL_PER_END_DATE=""), 2025) == (
        "RETAINED",
        "PR_2025_OVERLAP",
    )
