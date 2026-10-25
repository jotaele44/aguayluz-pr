import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "validate_prdoh_sdwis_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("validate_prdoh_sdwis_reconciliation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def test_frozen_reconciliation_passes():
    assert M.main([]) == 0


def test_f01_same_name_different_id_denied():
    assert not M.bind_system("PR0000001", "PR0000002")


def test_f02_normalized_name_only_denied():
    assert not M.bind_system(None, None)


def test_f03_count_equality_only_denied():
    assert not M.bind_system("PR0000001", "PR0000002")


def test_f04_four_digit_padding_without_crosswalk_denied():
    assert not M.bind_system(
        "4945", "PR0004945",
        left_namespace="PRASA_PWS_4DIGIT_SHORTHAND",
        right_namespace="PWSID_9CHAR_AUTHORITY_GRADE",
    )


def test_f05_exact_stable_pwsid_allowed():
    assert M.bind_system("PR0401404", "PR0401404")


def test_f06_missing_prdoh_violation_id_denied():
    assert not M.bind_violation(None, "1234567")


def test_f07_single_composite_is_discovery_only():
    assert M.composite_disposition(1) == "DISCOVERY_ONLY_NO_BIND"


def test_f08_multiple_composites_are_review_tie():
    assert M.composite_disposition(2) == "REVIEW_TIE_NO_BIND"


def test_f09_arrow_cannot_be_calendar_date():
    assert M.arrow_disposition("--->", "2025-01-01", "2025-01-01") == "DENY"


def test_f10_open_ended_arrow_overlapping_2025_retained():
    assert M.arrow_disposition("--->", "", "2024-10-17") == "RETAIN_OPEN_ENDED_2025_OVERLAP"


def test_f11_enforcement_id_cannot_substitute_for_violation_id():
    assert not M.bind_violation(None, "EFL")


def test_f12_join_multiplication_fails():
    with pytest.raises(ValueError):
        M.enforce_join_conservation(10, 1, 11)


def test_f13_row_disappearance_fails():
    with pytest.raises(ValueError):
        M.enforce_join_conservation(10, 1, 9)


def test_f14_source_only_is_terminal_no_bind():
    assert M.composite_disposition(0) == "SOURCE_ONLY_NO_BIND"
