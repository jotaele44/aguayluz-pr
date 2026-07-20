"""Tests for the OSHA enforcement ingest (scripts/ingest_osha.py)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_osha import (  # noqa: E402
    SOURCE_PREFIX,
    _isodate,
    build_events,
    merge,
)

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "tests" / "fixtures" / "osha_inspections_sample.json").read_text())
SCHEMA = json.loads((ROOT / "schemas" / "service_event.schema.json").read_text())
CANON = {"BAYAMON": "Bayamón", "PONCE": "Ponce", "CAROLINA": "Carolina"}


def _events():
    return build_events(DOC, CANON, "PR")


def test_isodate_normalizes_and_handles_null():
    assert _isodate("2026-05-12") == "2026-05-12T00:00:00Z"
    assert _isodate(None) is None
    assert _isodate("null") is None


def test_only_pr_inspections_kept():
    events = _events()
    # The FL record (Miami) is filtered out; the three PR ones remain.
    assert len(events) == 3
    assert all(e["source_ref"].startswith(SOURCE_PREFIX) for e in events)


def test_event_shape_and_status_text_carries_osha_fields():
    ev = {e["source_ref"]: e for e in _events()}["OSHA ENFORCEMENT activity_nr=317405066"]
    assert ev["event_id"] == "AYL_EVT_20260512_OSHA-317405066"
    assert ev["event_type"] == "unknown"
    assert ev["evidence_tier"] == "T1"
    assert ev["municipality"] == "Bayamón"
    # Fatality/Catastrophe inspections need a human review before acceptance.
    assert ev["review_status"] == "needs_review"
    # Promoter-parseable hints live in status_text (schema forbids extra keys).
    assert "insp_type='Fatality/Catastrophe'" in ev["status_text"]
    assert "activity_nr=317405066" in ev["status_text"]


def test_programmed_inspection_is_accepted_not_review():
    ev = {e["source_ref"]: e for e in _events()}["OSHA ENFORCEMENT activity_nr=317777042"]
    assert ev["review_status"] == "accepted"


def test_events_validate_against_service_event_schema():
    import jsonschema

    for ev in _events():
        jsonschema.validate(ev, SCHEMA)


def test_merge_is_idempotent_and_preserves_other_sources():
    other = {"event_id": "AYL_EVT_20240101_EPA", "source_ref": "EPA ECHO CWA source_id=X"}
    first = merge([other], _events())
    second = merge(first, _events())
    assert len(first) == len(second)  # re-run replaces, does not duplicate
    assert any(e["source_ref"].startswith("EPA ECHO CWA") for e in second)  # other source kept
    osha = [e for e in second if e["source_ref"].startswith(SOURCE_PREFIX)]
    assert len(osha) == 3
