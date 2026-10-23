import json
from pathlib import Path

import pytest
from scripts.adjudicate_salud_sdwis_2025_residue import adjudicate, run


def _item(reason: str, **row):
    return {
        "source_line": 10,
        "source_row_sha256": "a" * 64,
        "reason": reason,
        "source_row": row,
    }


def test_enforcement_only_is_resolved_excluded():
    item = _item(
        "MISSING_PWSID_OR_VIOLATION_ID",
        PWSID="PR0000001",
        VIOLATION_ID="",
        ENFORCEMENT_ID="E-1",
    )
    assert adjudicate(item, 2025) == (
        "RESOLVED_EXCLUDED",
        "ENFORCEMENT_ONLY_WITHOUT_VIOLATION_ID",
    )


def test_missing_violation_id_with_violation_content_fails_closed():
    item = _item(
        "MISSING_PWSID_OR_VIOLATION_ID",
        PWSID="PR0000001",
        VIOLATION_ID="",
        ENFORCEMENT_ID="E-1",
        VIOLATION_CODE="MCL",
    )
    assert adjudicate(item, 2025)[0] == "UNRESOLVED"


def test_literal_arrow_sentinel_remains_unresolved():
    item = _item(
        "INVALID_END_DATE",
        PWSID="PR0000001",
        VIOLATION_ID="V-1",
        NON_COMPL_PER_BEGIN_DATE="10/17/2024",
        NON_COMPL_PER_END_DATE="--->",
    )
    assert adjudicate(item, 2025) == (
        "UNRESOLVED",
        "UNVERIFIED_LITERAL_END_DATE_SENTINEL",
    )


def test_begin_after_target_year_is_excluded_even_with_unbound_end_token():
    item = _item(
        "INVALID_END_DATE",
        PWSID="PR0000001",
        VIOLATION_ID="V-1",
        NON_COMPL_PER_BEGIN_DATE="01/01/2026",
        NON_COMPL_PER_END_DATE="--->",
    )
    assert adjudicate(item, 2025) == (
        "RESOLVED_EXCLUDED",
        "NONCOMPLIANCE_BEGINS_AFTER_TARGET_YEAR",
    )


def test_receipt_conserves_rows_and_preserves_input(tmp_path: Path):
    source = tmp_path / "unresolved.jsonl"
    items = [
        _item(
            "MISSING_PWSID_OR_VIOLATION_ID",
            PWSID="PR0000001",
            VIOLATION_ID="",
            ENFORCEMENT_ID="E-1",
        ),
        _item(
            "INVALID_END_DATE",
            PWSID="PR0000002",
            VIOLATION_ID="V-2",
            NON_COMPL_PER_BEGIN_DATE="01/01/2026",
            NON_COMPL_PER_END_DATE="--->",
        ),
        _item(
            "INVALID_END_DATE",
            PWSID="PR0000003",
            VIOLATION_ID="V-3",
            NON_COMPL_PER_BEGIN_DATE="01/01/2025",
            NON_COMPL_PER_END_DATE="--->",
        ),
    ]
    source.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in items),
        encoding="utf-8",
    )
    before = source.read_bytes()
    output = tmp_path / "receipt.json"
    receipt = run(
        source,
        output,
        target_year=2025,
        predecessor_source_rows=13,
        predecessor_retained=3,
        predecessor_excluded=7,
    )
    assert source.read_bytes() == before
    assert receipt["adjudication"]["resolved_excluded"] == 2
    assert receipt["adjudication"]["unresolved"] == 1
    assert receipt["adjudication"]["row_conservation_delta"] == 0
    assert receipt["revised_source_arithmetic"] == {
        "source": 13,
        "retained": 3,
        "excluded": 9,
        "unresolved": 1,
        "accounted": 13,
        "delta": 0,
        "state": "PASS",
    }
    assert receipt["certification_state"] == "OPEN"


def test_expected_hash_mismatch_fails_closed(tmp_path: Path):
    source = tmp_path / "unresolved.jsonl"
    source.write_text(json.dumps(_item("OTHER")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash drift"):
        run(
            source,
            tmp_path / "receipt.json",
            target_year=2025,
            expected_input_sha256="0" * 64,
        )
