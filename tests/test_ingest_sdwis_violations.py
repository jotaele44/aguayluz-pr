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
    # county_served "Bayamon Municipio,..." (unaccented) -> canonical "Bayamón".
    muni = municipality_from_geo(GEO_BY["PR0002000"], CANON)
    assert muni == "Bayamón"


def test_tier1_microbial_is_never_inferred_as_boil_water():
    rows = {r["event_id"]: r for r in _events()}
    # PR0002000 9100777: health_based=Y, tier=1, rule_group=100 (coliform). A Tier-1
    # public-notice requirement does not prove a boil-water advisory was issued, so it
    # stays a violation; pn_tier and rule_group stay in status_text for the alert layer.
    v = rows["AYL_EVT_20240915_PR0002000_9100777"]
    assert v["event_type"] == "water_quality_violation"
    assert "pn_tier=1" in v["status_text"] and "rule_group=100" in v["status_text"]
    assert v["review_status"] == "needs_review"  # health-based + unresolved
    # PR0002591 9001234: health_based=Y, tier=2 -> water_quality_violation
    assert rows["AYL_EVT_20230401_PR0002591_9001234"]["event_type"] == "water_quality_violation"
    # PR0002000 9200888: health_based=Y, tier=1, rule_group=210 (disinfection
    # byproducts) -> water_quality_violation
    assert rows["AYL_EVT_20241001_PR0002000_9200888"]["event_type"] == "water_quality_violation"
    assert all(r["event_type"] != "boil_water" for r in rows.values())


def test_events_are_schema_shaped():
    import re

    rows = _events()
    assert len(rows) == 5
    req = set(SCHEMA["required"])
    allowed = set(SCHEMA["properties"])
    enums = {k: set(v["enum"]) for k, v in SCHEMA["properties"].items() if "enum" in v}
    pat = re.compile(SCHEMA["properties"]["event_id"]["pattern"])
    for r in rows:
        assert req <= set(r) and set(r) <= allowed
        assert r["event_type"] == "water_quality_violation"
        for k, choices in enums.items():
            if k in r:
                assert r[k] in choices
        assert pat.match(r["event_id"])


def test_health_based_unresolved_routes_to_review():
    rows = {r["event_id"]: r for r in _events()}
    # PR0002591 violation 9001234: health_based=Y, compliance=O (open) -> needs_review
    assert rows["AYL_EVT_20230401_PR0002591_9001234"]["review_status"] == "needs_review"
    # PR0002000 7613411: health_based=N, compliance=R -> accepted
    assert rows["AYL_EVT_20140701_PR0002000_7613411"]["review_status"] == "accepted"


def test_population_carried_as_int():
    rows = {r["event_id"]: r for r in _events()}
    assert rows["AYL_EVT_20230401_PR0002591_9001234"]["reported_customers_or_users"] == 1200


def test_merge_replaces_sdwis_preserves_others():
    existing = [
        {"event_id": "AYL_EVT_20260606_toa_alta_outage", "event_type": "outage",
         "source_ref": "LUMA outages_by_town"},
        {"event_id": "AYL_EVT_20140701_PR0002000_7613411", "event_type": "water_quality_violation",
         "source_ref": "EPA SDWIS VIOLATION pwsid=PR0002000 violation_id=7613411", "confidence": 1},
    ]
    out = {e["event_id"]: e for e in merge(existing, _events())}
    assert "AYL_EVT_20260606_toa_alta_outage" in out  # non-SDWIS preserved
    assert out["AYL_EVT_20140701_PR0002000_7613411"]["confidence"] == 80  # SDWIS replaced
