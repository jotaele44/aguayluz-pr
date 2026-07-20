"""Tests for the Centinelas dispatch -> service_event adapter."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "ingest_centinelas_dispatch",
    Path(__file__).resolve().parent.parent / "scripts" / "ingest_centinelas_dispatch.py",
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


def test_event_type_priority():
    assert mod.event_type_for(["potable_water", "boil_water"]) == "boil_water"
    assert mod.event_type_for(["water_quality"]) == "water_quality_violation"
    assert mod.event_type_for(["power_grid"]) == "outage"
    assert mod.event_type_for(["wastewater"]) == "contamination_incident"
    assert mod.event_type_for([]) == "project_update"


def test_payload_maps_to_service_event():
    payload = {
        "schema_version": "1.0", "item_id": "w1",
        "source_url": "https://example.pr/prasa-boil",
        "title": "PRASA boil water advisory for Ponce",
        "published_at": "2026-07-15T00:00:00+00:00",
        "confidence": 0.8, "domain_tags": ["potable_water", "boil_water"],
        "municipality": "Ponce",
    }
    row = mod.payload_to_event(payload)
    assert row["event_type"] == "boil_water"
    assert row["municipality"] == "Ponce"
    assert row["evidence_tier"] == "T3"
    assert row["review_status"] == "needs_review"
    assert row["confidence"] == 80
    assert row["source_ref"] == "https://example.pr/prasa-boil"
    assert row["event_id"].startswith("AYL_EVT_20260715_")


def test_untagged_signal_is_project_update():
    payload = {"source_url": "https://x.pr/a", "title": "Nueva planta anunciada",
               "published_at": "2026-01-02T00:00:00+00:00"}
    row = mod.payload_to_event(payload)
    assert row["event_type"] == "project_update"
