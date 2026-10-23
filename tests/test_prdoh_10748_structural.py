import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "validate_prdoh_10748_structural.py"
SPEC = importlib.util.spec_from_file_location("validate_prdoh_10748_structural", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

same_system = MODULE.same_system
admit_to_violation_denominator = MODULE.admit_to_violation_denominator
enforce_join_conservation = MODULE.enforce_join_conservation
validate_receipt = MODULE.validate_receipt

RECEIPT = REPO / "data" / "certification" / "prdoh_10748_structural_v1.json"


def test_frozen_receipt_passes():
    validate_receipt(json.loads(RECEIPT.read_text(encoding="utf-8")))


def test_same_name_different_pwsid_does_not_bind():
    assert not same_system(
        {"pwsid": "PR0000001", "system_name": "SAME NAME"},
        {"pwsid": "PR0000002", "system_name": "SAME NAME"},
    )


def test_normalized_name_alone_does_not_bind():
    assert not same_system(
        {"pwsid": None, "system_name": "ACUEDUCTO EJEMPLO"},
        {"pwsid": None, "system_name": "acueducto ejemplo"},
    )


def test_count_equality_does_not_bind():
    assert not same_system(
        {"pwsid": "PR0000001", "row_count": 121},
        {"pwsid": "PR0000002", "row_count": 121},
    )


def test_stable_pwsid_match_binds():
    assert same_system(
        {"pwsid": "PR0401404", "system_name": "HACIENDA LA BALEAR"},
        {"pwsid": "PR0401404", "system_name": "OCR VARIANT"},
    )


@pytest.mark.parametrize("kind", ["REFERENCE_TABLE", "TREATMENT_TABLE", "NARRATIVE", "HEADER_OR_FOOTER", "NONDATA_IMAGE"])
def test_non_violation_regions_never_enter_violation_denominator(kind):
    assert not admit_to_violation_denominator(kind)


def test_violation_region_is_admissible():
    assert admit_to_violation_denominator("VIOLATION_TABLE")


def test_join_multiplication_fails_closed():
    with pytest.raises(ValueError):
        enforce_join_conservation(10, 1, 11)


def test_join_disappearance_fails_closed():
    with pytest.raises(ValueError):
        enforce_join_conservation(10, 1, 9)


def test_declared_one_to_many_join_can_conserve():
    enforce_join_conservation(10, 2, 20)
