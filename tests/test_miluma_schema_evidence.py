import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RECEIPT = REPO / "governance" / "miluma_schema_evidence.json"

_spec = importlib.util.spec_from_file_location(
    "miluma_schema_gate", REPO / "scripts" / "validate_miluma_schema_evidence.py"
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _doc():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_receipt_passes_bounded_gate():
    gate.validate(_doc())


def test_archive_cannot_promote_live_schema():
    doc = _doc()
    doc["live_schema_state"] = "FROZEN"
    try:
        gate.validate(doc)
    except AssertionError:
        pass
    else:
        raise AssertionError("historical archive must not promote current live schema")


def test_source_absence_cannot_become_zero():
    doc = _doc()
    doc["promotion_rules"]["source_unavailable_is_zero"] = True
    try:
        gate.validate(doc)
    except AssertionError:
        pass
    else:
        raise AssertionError("source absence must remain distinct from zero")


def test_snapshot_change_cannot_become_restoration():
    doc = _doc()
    doc["promotion_rules"]["snapshot_change_is_restoration"] = True
    try:
        gate.validate(doc)
    except AssertionError:
        pass
    else:
        raise AssertionError("snapshot change alone must not certify restoration")


def test_preb_metrics_are_comparators_not_live_identity():
    doc = _doc()
    assert doc["preb_comparison"]["live_snapshot_identity"] is False
    assert doc["preb_comparison"]["restoration_event_identity"] is False
