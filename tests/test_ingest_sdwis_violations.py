import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_sdwis_violations import (  # noqa: E402
    _isodate,
    build_events,
    load_muni_canonical,
    merge,
    municipality_from_geo,
)

ROOT = Path(__file__).resolve().parents[1]
VIOL = json.loads((ROOT / "tests" / "fixtures" / "sdwis_violations_sample.json").read_text())
GEO = json.loads((ROOT / "tests" / "fixtures" / "sdwis_geographic_area_sample.json").read_text())
SCHEMA = json.loads((ROOT / "schemas" / "service_event.schema.json").read_text())
CANON = load_muni_canonical(ROOT / "data" / "geo" / "pr_municipios.geojson")
GEO_BY = {g["pwsid"]: g for g in GEO}


def _events():
    return build_events(VIOL, GEO_BY, CANON)


def test_isodate_normalizes_and_handles_null():
    assert _isodate("2014-07-01 00:00:00") == "2014-07-01T00:00:00Z"
    assert _isodate(None) is None
    assert _isodate("null") is None


def test_municipality_resolved_to_canonical_accented():
    # Legacy-only geographic projection: source county text -> canonical display name.
    muni = municipality_from_geo(GEO_BY["PR0002000"], CANON)
    assert muni == "Bayamón"


def test_sdwis_violation_never_infers_boil_water_advisory():
    rows = {row["event_id"]: row for row in _events()}

    microbial = rows["AYL_EVT_20240915_PR0002000_9100777"]
    assert microbial["event_type"] == "water_quality_violation"
    assert microbial["review_status"] == "needs_review"
    assert "advisory=not_established_by_sdwis_violation_alone" in microbial["status_text"]

    tier2 = rows["AYL_EVT_20230401_PR0002591_9001234"]
    assert tier2["event_type"] == "water_quality_violation"

    disinfectant = rows["AYL_EVT_20241001_PR0002000_9200888"]
    assert disinfectant["event_type"] == "water_quality_violation"


def test_events_are_schema_shaped():
    import re

    rows = _events()
    assert len(rows) == 5
    req = set(SCHEMA["required"])
    allowed = set(SCHEMA["properties"])
    enums = {
        key: set(value["enum"])
        for key, value in SCHEMA["properties"].items()
        if "enum" in value
    }
    pattern = re.compile(SCHEMA["properties"]["event_id"]["pattern"])
    for row in rows:
        assert req <= set(row) and set(row) <= allowed
        assert row["event_type"] == "water_quality_violation"
        for key, choices in enums.items():
            if key in row:
                assert row[key] in choices
        assert pattern.match(row["event_id"])


def test_health_based_unresolved_routes_to_review():
    rows = {row["event_id"]: row for row in _events()}
    assert rows["AYL_EVT_20230401_PR0002591_9001234"]["review_status"] == "needs_review"
    assert rows["AYL_EVT_20140701_PR0002000_7613411"]["review_status"] == "accepted"


def test_population_carried_as_int():
    rows = {row["event_id"]: row for row in _events()}
    assert rows["AYL_EVT_20230401_PR0002591_9001234"]["reported_customers_or_users"] == 1200


def test_merge_replaces_sdwis_preserves_others():
    existing = [
        {
            "event_id": "AYL_EVT_20260606_toa_alta_outage",
            "event_type": "outage",
            "source_ref": "LUMA outages_by_town",
        },
        {
            "event_id": "AYL_EVT_20140701_PR0002000_7613411",
            "event_type": "water_quality_violation",
            "source_ref": "EPA SDWIS VIOLATION pwsid=PR0002000 violation_id=7613411",
            "confidence": 1,
        },
    ]
    out = {event["event_id"]: event for event in merge(existing, _events())}
    assert "AYL_EVT_20260606_toa_alta_outage" in out
    assert out["AYL_EVT_20140701_PR0002000_7613411"]["confidence"] == 80
