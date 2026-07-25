import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_usgs_quakes import (  # noqa: E402
    DEFAULT_MIN_MAGNITUDE,
    SOURCE_PREFIX,
    build_events,
    merge,
)

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "usgs_pr_quakes_sample.json"
SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "service_event.schema.json"
EVENT_ID_RE = re.compile(r"^AYL_EVT_[0-9]{8}_[A-Za-z0-9_-]+$")


def _doc():
    return json.loads(FIXTURE.read_text())


def test_build_events_filters_bbox_and_magnitude():
    rows = build_events(_doc())
    # Fixture has 4 features: 2 qualify, 1 below the mag floor, 1 outside the bbox.
    ids = {r["source_ref"] for r in rows}
    assert len(rows) == 2
    assert f"{SOURCE_PREFIX}:pr71401234" in ids  # M4.6 in PR
    assert f"{SOURCE_PREFIX}:pr71405678" in ids  # M3.1 in PR
    assert f"{SOURCE_PREFIX}:pr71409999" not in ids  # M1.8 < 2.5 floor
    assert f"{SOURCE_PREFIX}:us70008888" not in ids  # outside PR bbox


def test_min_magnitude_override():
    rows = build_events(_doc(), min_magnitude=4.0)
    assert len(rows) == 1
    assert rows[0]["source_ref"] == f"{SOURCE_PREFIX}:pr71401234"


def test_event_id_and_time_shape():
    rows = build_events(_doc())
    r = next(x for x in rows if x["source_ref"] == f"{SOURCE_PREFIX}:pr71401234")
    assert EVENT_ID_RE.match(r["event_id"])
    assert r["event_id"].startswith("AYL_EVT_")
    assert r["start_time"].endswith("Z") and "T" in r["start_time"]
    assert r["evidence_tier"] == "T1" and r["review_status"] == "accepted"
    assert "M4.6" in r["status_text"]


def test_rows_validate_against_service_event_schema():
    schema = json.loads(SCHEMA.read_text())
    required = set(schema["required"])
    allowed = set(schema["properties"])
    enums = {k: set(v["enum"]) for k, v in schema["properties"].items() if "enum" in v}
    rows = build_events(_doc())
    assert rows
    for r in rows:
        assert required <= set(r), f"missing fields in {r['event_id']}"
        assert set(r) <= allowed, f"extra fields in {r['event_id']}"
        for k, choices in enums.items():
            if k in r:
                assert r[k] in choices


def test_merge_preserves_non_usgs_eq_and_replaces_usgs_eq():
    existing = [
        {"event_id": "AYL_EVT_20250101_NWS-1-2", "source_ref": "NWS-IDP-PROD-1"},
        {"event_id": "AYL_EVT_20250101_SDWIS-x", "source_ref": "SDWIS:PR123"},
        {"event_id": "AYL_EVT_20240101_USGS-EQ-pr71401234",
         "source_ref": f"{SOURCE_PREFIX}:pr71401234", "confidence": 1},
    ]
    new = build_events(_doc())
    out = {r["event_id"]: r for r in merge(existing, new)}
    # Non-USGS-EQ rows survive untouched.
    assert "AYL_EVT_20250101_NWS-1-2" in out
    assert "AYL_EVT_20250101_SDWIS-x" in out
    # The stale USGS-EQ row is replaced by the freshly built one (confidence 85).
    replaced = next(r for r in out.values()
                    if r["source_ref"] == f"{SOURCE_PREFIX}:pr71401234")
    assert replaced["confidence"] == 85


def test_default_min_magnitude_constant():
    assert DEFAULT_MIN_MAGNITUDE == 2.5


def test_exact_epicenter_persisted_on_row():
    # The exact USGS epicenter (geometry.coordinates) is carried on the row so alert
    # promotion can link by real distance instead of a municipality centroid.
    rows = build_events(_doc())
    r = next(x for x in rows if x["source_ref"] == f"{SOURCE_PREFIX}:pr71401234")
    assert isinstance(r["lat"], float) and isinstance(r["lon"], float)
    # PR region: negative longitude, positive latitude.
    assert 17.0 <= r["lat"] <= 19.0
    assert -68.0 <= r["lon"] <= -65.0
