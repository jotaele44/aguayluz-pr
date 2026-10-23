import importlib.util
from pathlib import Path

import pytest

_SCRIPT=Path(__file__).resolve().parent.parent/"scripts"/"freeze_sdwis_pr_pws_inventory.py"
_SPEC=importlib.util.spec_from_file_location("freeze_sdwis_pr_pws_inventory",_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
quarter_inventory = _MODULE.quarter_inventory
select_latest_pr = _MODULE.select_latest_pr


def _row(q,pwsid,activity="A",ptype="CWS"):
    return {
        "SUBMISSIONYEARQUARTER":q,
        "PWSID":pwsid,
        "PWS_ACTIVITY_CODE":activity,
        "PWS_TYPE_CODE":ptype,
        "PWS_NAME":"Fixture",
    }


def test_select_latest_pr_preserves_activity_states():
    rows=[
        _row("2026Q2","PR0000001","A"),
        _row("2026Q3","PR0000001","A"),
        _row("2026Q3","PR0000002","I","TNCWS"),
    ]
    out=select_latest_pr(rows)
    assert out["latest_quarter"]=="2026Q3"
    assert out["latest_row_count"]==2
    assert out["active_count"]==1
    assert out["inactive_count"]==1
    assert out["active_pwsids"]==["PR0000001"]
    assert out["activity_counts"]=={"A":1,"I":1}


def test_select_latest_pr_rejects_duplicate_stable_id():
    rows=[_row("2026Q3","PR0000001"),_row("2026Q3","PR0000001")]
    with pytest.raises(ValueError,match="uniqueness"):
        select_latest_pr(rows)


def test_select_latest_pr_rejects_malformed_pwsid():
    with pytest.raises(ValueError,match="malformed"):
        select_latest_pr([_row("2026Q3","PR123")])


def test_quarter_inventory_uses_same_period_stable_ids():
    rows = [
        _row("2025Q3", "PR0000001", "A", "CWS"),
        _row("2025Q3", "PR0000002", "A", "NTNCWS"),
        _row("2026Q3", "PR0000003", "A", "TNCWS"),
    ]
    out = quarter_inventory(rows, "2025Q3")
    assert out["rows"] == 2
    assert out["active_count"] == 2
    assert out["active_pwsids"] == ["PR0000001", "PR0000002"]
    assert out["active_type_counts"] == {"CWS": 1, "NTNCWS": 1}
