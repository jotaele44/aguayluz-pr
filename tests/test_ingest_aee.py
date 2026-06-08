"""Tests for scripts/ingest_aee.py — the per-municipality AEE/LUMA outage adapter."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aguayluz import REPO_ROOT  # noqa: E402
from aguayluz.models import ServiceEvent  # noqa: E402
from federation_export import build_streams  # noqa: E402
from fetch_luma_live import municipio_keys  # noqa: E402
from ingest_aee import build_events, unaccent_upper  # noqa: E402

TS = "2025-03-03T01:38:40Z"
REF = "https://example/outages_by_town.json"

# A small canonical geo index (mirrors data/geo/pr_municipios.json, keyed unaccent/upper).
GEO = {
    "CATANO": {"name": "Cataño", "lat": 18.444614, "lon": -66.148819},
    "SAN JUAN": {"name": "San Juan", "lat": 18.422249, "lon": -66.069081},
    "GUAYNABO": {"name": "Guaynabo", "lat": 18.344357, "lon": -66.114056},
}

# Shape verified against the real LUMA feed: {MUNICIPIO: [{zone, area}, ...]}
SAMPLE = {
    "CATANO": [],                                   # listed but no active outage
    "SAN JUAN": [{"zone": "CUPEY", "area": "SAN JUAN"},
                 {"zone": "SABANA LLANA", "area": "SAN JUAN"}],
    "GUAYNABO": [{"zone": "FRAILES", "area": "GUAYNABO"}],
}

PATTERN = re.compile(r"^AYL_EVT_[0-9]{8}_[A-Za-z0-9_-]+$")


def test_unaccent_upper_join_key():
    assert unaccent_upper("Cataño") == "CATANO"
    assert unaccent_upper("Río Grande") == "RIO GRANDE"


def test_live_fetch_builds_api_keys_from_geodata():
    # The live MiLUMA fetcher must query the API with ALLCAPS/unaccented municipio names.
    keys = municipio_keys(REPO_ROOT / "data/geo/pr_municipios.json")
    assert len(keys) == 78
    assert "SAN JUAN" in keys and "CATANO" in keys and "SAN SEBASTIAN" in keys
    assert all(k == k.upper() and k.isascii() for k in keys)


def test_empty_municipio_emits_no_event():
    events = build_events(SAMPLE, TS, GEO, REF)
    assert all(e["municipality"] != "Cataño" for e in events)  # CATANO had []
    assert len(events) == 3  # 2 San Juan zones + 1 Guaynabo zone


def test_rows_are_schema_valid_and_well_formed():
    events = build_events(SAMPLE, TS, GEO, REF)
    for e in events:
        ServiceEvent(**e)  # pydantic + jsonschema (additionalProperties=false)
        assert e["event_type"] == "outage"
        assert e["evidence_tier"] == "T2"
        assert e["review_status"] == "needs_review"
        assert PATTERN.match(e["event_id"])
        assert e["start_time"] == TS
    assert len({e["event_id"] for e in events}) == len(events)  # unique ids


def test_name_normalization_and_zone_detail():
    events = build_events(SAMPLE, TS, GEO, REF)
    sj = next(e for e in events if e["zone"] == "CUPEY")
    assert sj["municipality"] == "San Juan"          # canonical accented name
    assert sj["affected_area"] == "San Juan / CUPEY"
    assert sj["event_id"].startswith("AYL_EVT_20250303_")  # date from snapshot ts


def test_unresolved_municipio_still_emits_without_municipality():
    events = build_events({"NOWHERE CITY": [{"zone": "Z", "area": "NOWHERE CITY"}]}, TS, {}, REF)
    assert len(events) == 1
    assert events[0]["municipality"] is None
    assert events[0]["affected_area"].startswith("Nowhere City")
    ServiceEvent(**events[0])  # still schema-valid


def test_municipio_granularity_aggregates_zones():
    events = build_events(SAMPLE, TS, GEO, REF, granularity="municipio")
    assert len(events) == 2  # San Juan + Guaynabo (Cataño had no outage)
    sj = next(e for e in events if e["municipality"] == "San Juan")
    assert sj["affected_area"] == "San Juan"            # no zone suffix in aggregate
    assert "CUPEY" in sj["zone"] and "SABANA LLANA" in sj["zone"]  # zones collapsed
    for e in events:
        ServiceEvent(**e)
        assert PATTERN.match(e["event_id"])
    assert len({e["event_id"] for e in events}) == len(events)


def test_both_granularities_are_idempotent():
    for g in ("zone", "municipio"):
        a = build_events(SAMPLE, TS, GEO, REF, granularity=g)
        b = build_events(SAMPLE, TS, GEO, REF, granularity=g)
        assert [e["event_id"] for e in a] == [e["event_id"] for e in b]


def test_federation_export_attaches_location_and_located_in():
    events = build_events(SAMPLE, TS, GEO, REF)
    streams = build_streams([], events, "t", GEO)
    ev = next(e for e in streams["entities"]
              if e["entity_type"] == "service_event" and "San Juan" in e["name"])
    assert ev["location"] == {"lat": 18.422249, "lon": -66.069081, "municipality": "San Juan"}
    rels = {r["relationship_type"] for r in streams["relationships"]}
    assert "located_in" in rels
    # the two San Juan zone-events converge on one municipality node
    munis = [e for e in streams["entities"] if e["entity_type"] == "municipality"]
    assert any(m["name"] == "San Juan" for m in munis)
