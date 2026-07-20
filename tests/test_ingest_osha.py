"""Tests for the OSHA enforcement ingest (scripts/ingest_osha.py)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_osha import (  # noqa: E402
    SOURCE_PREFIX,
    _build_filter,
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


def test_build_filter_shapes():
    # Single condition -> flat object; state + since -> and-wrapper with gte.
    # (Shapes verified against the live DOL v4 API.)
    assert _build_filter("PR", None) == {"field": "site_state", "operator": "eq", "value": "PR"}
    assert _build_filter("PR", "2024-01-01") == {
        "and": [
            {"field": "site_state", "operator": "eq", "value": "PR"},
            {"field": "open_date", "operator": "gte", "value": "2024-01-01"},
        ]
    }
    assert _build_filter("", None) is None


def test_isodate_normalizes_and_handles_null():
    assert _isodate("2026-05-12") == "2026-05-12T00:00:00Z"
    assert _isodate(None) is None
    assert _isodate("null") is None


def test_only_pr_inspections_kept():
    events = _events()
    # The FL record (Miami) is filtered out; the five PR ones remain.
    assert len(events) == 5
    assert all(e["source_ref"].startswith(SOURCE_PREFIX) for e in events)


def test_coded_accident_inspection_flags_review():
    # Real DOL v4 insp_type is a single-letter IMIS code; an open "A" (accident)
    # inspection must still be flagged for review.
    ev = {e["source_ref"]: e for e in _events()}["OSHA ENFORCEMENT activity_nr=320500777"]
    assert ev["review_status"] == "needs_review"
    assert "insp_type='A'" in ev["status_text"]


def test_closed_inspection_carries_end_time_and_no_review():
    ev = {e["source_ref"]: e for e in _events()}["OSHA ENFORCEMENT activity_nr=310100200"]
    # A closed historical fatality inspection records its close date in end_time
    # and does not re-enter the review queue.
    assert ev["end_time"] == "2019-11-20T00:00:00Z"
    assert ev["review_status"] == "accepted"
    assert "case=closed" in ev["status_text"]


def test_open_inspection_has_no_end_time():
    ev = {e["source_ref"]: e for e in _events()}["OSHA ENFORCEMENT activity_nr=317405066"]
    assert ev["end_time"] is None
    assert "case=open" in ev["status_text"]


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
    assert len(osha) == 5
