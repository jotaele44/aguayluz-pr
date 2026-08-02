"""scripts/ingest_nhc_storms.py — NHC active tropical cyclones.

Every built row is validated against the real schemas/service_event.schema.json.

Fixture note: `nhc_current_storms.json` is a REAL capture of
https://www.nhc.noaa.gov/CurrentStorms.json, untrimmed. It holds one eastern Pacific
storm, so it exercises the *exclusion* path end to end. There was no Atlantic system
anywhere on the globe when it was taken, and NHC publishes no archive of this file, so
the positive cases are CONSTRUCTED inline from the captured object's exact shape and are
labelled as such — the same approach `test_ingest_usgs_samples.py` takes for its
unitless-result case.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ingest_nhc_storms import (  # noqa: E402
    WATCH_LAT_MAX,
    WATCH_LAT_MIN,
    WATCH_LON_MAX,
    WATCH_LON_MIN,
    build_events,
    is_atlantic,
    merge,
    threatens_pr,
)

FIXTURES = REPO / "tests" / "fixtures"
EVENT_SCHEMA = json.loads((REPO / "schemas" / "service_event.schema.json").read_text())


def _capture() -> dict:
    return json.loads((FIXTURES / "nhc_current_storms.json").read_text())


def _storm(**over) -> dict:
    """An Atlantic hurricane bearing down on PR, in the captured object's exact shape.

    CONSTRUCTED, not captured — see the module docstring. Field names, types and string
    formats (numeric-string intensity, millisecond timestamps) are copied verbatim from
    the real eastern Pacific storm in `nhc_current_storms.json`.
    """
    base = {
        "id": "al052026",
        "binNumber": "AT1",
        "name": "Bertha",
        "classification": "HU",
        "intensity": "85",
        "pressure": "968",
        "latitude": "17.4N",
        "longitude": "64.2W",
        "latitudeNumeric": 17.4,
        "longitudeNumeric": -64.2,
        "movementDir": 285,
        "movementSpeed": 13,
        "lastUpdate": "2026-08-02T03:00:00.000Z",
        "publicAdvisory": {
            "advNum": "014",
            "issuance": "2026-08-02T03:00:00.000Z",
            "url": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
        },
    }
    base.update(over)
    return base


def _doc(*storms) -> dict:
    return {"activeStorms": list(storms)}


# ── the real capture ──────────────────────────────────────────────────────────
def test_real_capture_yields_no_pr_event():
    """Genevieve (ep072026) sat at 23.5N 136.0W — about 11,000 km from San Juan.

    Without the basin filter she would have raised a Puerto Rico weather event, which is
    exactly the bug this test exists to prevent.
    """
    events, skipped = build_events(_capture())
    assert events == []
    assert skipped["other_basin"] == 1


def test_eastern_pacific_ids_are_not_atlantic():
    assert not is_atlantic({"id": "ep072026"})
    assert not is_atlantic({"id": "cp012026"})
    assert is_atlantic({"id": "al052026"})
    assert is_atlantic({"id": "AL052026"})     # case-insensitive


# ── the approach corridor ─────────────────────────────────────────────────────
def test_storm_in_the_corridor_becomes_an_event():
    events, skipped = build_events(_doc(_storm()))
    assert len(events) == 1
    assert not any(skipped.values())
    jsonschema.validate(events[0], EVENT_SCHEMA)


def test_atlantic_storm_far_from_pr_is_filtered():
    """A Cabo Verde system is real but not yet actionable for PR."""
    events, skipped = build_events(_doc(_storm(latitudeNumeric=14.0, longitudeNumeric=-28.0)))
    assert events == []
    assert skipped["out_of_range"] == 1


def test_storm_without_a_position_is_counted_not_crashed():
    events, skipped = build_events(_doc(_storm(latitudeNumeric=None, longitudeNumeric=None)))
    assert events == []
    assert skipped["no_position"] == 1


def test_corridor_actually_contains_puerto_rico():
    """A box that excluded the island itself would be silently useless."""
    assert WATCH_LAT_MIN <= 18.2 <= WATCH_LAT_MAX
    assert WATCH_LON_MIN <= -66.5 <= WATCH_LON_MAX
    assert threatens_pr({"latitudeNumeric": 18.2, "longitudeNumeric": -66.5})


# ── event content ─────────────────────────────────────────────────────────────
def test_classification_and_intensity_survive_the_enum_collapse():
    """event_type has no member for an approaching hazard, so the real classification
    must be preserved in the text rather than lost to `service_interruption`."""
    event = build_events(_doc(_storm()))[0][0]
    assert event["event_type"] == "service_interruption"
    assert event["event_type"] in EVENT_SCHEMA["properties"]["event_type"]["enum"]
    assert "Hurricane" in event["status_text"]
    assert "Bertha" in event["status_text"]
    assert "85 kt" in event["status_text"]
    assert "968 mb" in event["status_text"]


def test_every_classification_code_is_expanded():
    for code, label in (("TD", "Tropical Depression"), ("TS", "Tropical Storm"),
                        ("HU", "Hurricane"), ("PTC", "Potential Tropical Cyclone")):
        event = build_events(_doc(_storm(classification=code)))[0][0]
        assert label in event["status_text"]


def test_unknown_classification_code_is_passed_through_not_dropped():
    event = build_events(_doc(_storm(classification="XX")))[0][0]
    assert "XX" in event["status_text"]


def test_event_carries_the_storm_position():
    event = build_events(_doc(_storm()))[0][0]
    assert event["lat"] == 17.4
    assert event["lon"] == -64.2


def test_source_ref_points_at_the_advisory():
    event = build_events(_doc(_storm()))[0][0]
    assert event["source_ref"].startswith("NHC-al052026")
    assert "MIATCPAT1" in event["source_ref"]


def test_millisecond_timestamps_are_trimmed():
    """NHC stamps `.000Z`; the schema's date-time format tolerates it, but the id is
    built from the date and the value is compared across runs."""
    event = build_events(_doc(_storm()))[0][0]
    assert event["start_time"] == "2026-08-02T03:00:00Z"


# ── identity + merge ──────────────────────────────────────────────────────────
def test_each_advisory_is_its_own_event():
    """Successive advisories are distinct published positions — together they are the
    track. Collapsing them onto one id would keep only the latest."""
    doc = _doc(_storm())
    later = _doc(_storm(publicAdvisory={
        "advNum": "015", "issuance": "2026-08-02T09:00:00.000Z",
        "url": "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"}))
    a = build_events(doc)[0][0]["event_id"]
    b = build_events(later)[0][0]["event_id"]
    assert a != b
    assert "adv014" in a and "adv015" in b


def test_re_running_the_same_advisory_is_idempotent():
    events = build_events(_doc(_storm()))[0]
    assert merge(merge([], events), events) == merge([], events)


def test_merge_preserves_earlier_advisories_and_other_sources():
    """Unlike the NWS merge, prior NHC rows are not dropped: an advisory that scrolled off
    CurrentStorms.json still happened, and the earlier positions are the track."""
    existing = [
        {"event_id": "AYL_EVT_20260801_NHC-al052026-adv010"},
        {"event_id": "AYL_EVT_20260801_NWS-123-456"},
    ]
    merged = merge(existing, build_events(_doc(_storm()))[0])
    ids = {e["event_id"] for e in merged}
    assert "AYL_EVT_20260801_NHC-al052026-adv010" in ids
    assert "AYL_EVT_20260801_NWS-123-456" in ids
    assert len(ids) == 3


def test_event_id_has_no_characters_the_schema_forbids():
    import re
    pattern = EVENT_SCHEMA["properties"]["event_id"].get("pattern")
    event = build_events(_doc(_storm()))[0][0]
    if pattern:
        assert re.match(pattern, event["event_id"]), event["event_id"]


def test_empty_and_malformed_documents_are_handled():
    assert build_events({})[0] == []
    assert build_events({"activeStorms": None})[0] == []
    assert build_events({"activeStorms": ["not a dict", {}]})[0] == []


def test_a_zero_event_run_leaves_the_file_byte_identical(tmp_path):
    """Regression: this file is written with default ensure_ascii by every sibling
    (ingest_nws_alerts, ingest_usgs_quakes, ingest_sdwis_violations). Writing raw UTF-8
    re-encodes ~4,900 accented municipality rows, so a run that adds NOTHING produces a
    whole-file diff and buries any real change."""
    out = tmp_path / "service_events.jsonl"
    existing = [{"event_id": "AYL_EVT_20260101_X", "affected_area": "Bayamón, Mayagüez",
                 "status_text": "Añasco"}]
    out.write_text("".join(json.dumps(r) + "\n" for r in existing))
    before = out.read_bytes()

    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ingest_nhc_storms.py"),
         "--src", str(FIXTURES / "nhc_current_storms.json"), "--out", str(out)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes() == before


# ── CLI ───────────────────────────────────────────────────────────────────────
def test_offline_dry_run_reports_the_filter(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ingest_nhc_storms.py"),
         "--src", str(FIXTURES / "nhc_current_storms.json"), "--dry-run"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "other_basin=1" in proc.stdout       # drops are reported, never silent


def test_offline_run_writes_valid_output(tmp_path):
    out = tmp_path / "service_events.jsonl"
    src = tmp_path / "storms.json"
    src.write_text(json.dumps(_doc(_storm())))
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ingest_nhc_storms.py"),
         "--src", str(src), "--out", str(out)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    for row in rows:
        jsonschema.validate(row, EVENT_SCHEMA)
