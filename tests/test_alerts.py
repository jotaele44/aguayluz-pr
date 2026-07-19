"""Alert system: schema validation, Pydantic models, VAL-001..010 pipeline,
seed integrity, SQLite build, and GeoJSON projection."""

from __future__ import annotations

import pytest
from jsonschema import ValidationError

from aguayluz.alert_db import (
    build_sqlite,
    events_to_geojson,
    load_edges,
    load_events,
    load_gaps,
    load_modules,
)
from aguayluz.alert_validation import COVERT_FLAG_VOCAB, validate_alert, validate_alerts
from aguayluz.alerts import ACTIVE_MODULES, AlertEvent, AlertModule
from aguayluz.models import validate_against_schema

# ---------------- schema: alert_event ----------------

def test_alert_event_valid(alert_event_valid):
    validate_against_schema("alert_event", alert_event_valid)
    AlertEvent(**alert_event_valid)


def test_alert_event_rejects_bad_id_pattern(alert_event_valid):
    bad = {**alert_event_valid, "alert_id": "carraizo-1"}
    with pytest.raises(ValidationError):
        validate_against_schema("alert_event", bad)


def test_alert_event_rejects_unknown_module(alert_event_valid):
    bad = {**alert_event_valid, "module_id": "MYSTERY_OPS"}
    with pytest.raises(ValidationError):
        validate_against_schema("alert_event", bad)


def test_alert_event_rejects_severity_over_5(alert_event_valid):
    bad = {**alert_event_valid, "severity": 6}
    with pytest.raises(ValidationError):
        validate_against_schema("alert_event", bad)


def test_alert_event_rejects_confidence_over_100(alert_event_valid):
    bad = {**alert_event_valid, "confidence": 101}
    with pytest.raises(ValidationError):
        validate_against_schema("alert_event", bad)


def test_alert_event_rejects_out_of_pr_bbox(alert_event_valid):
    bad = {**alert_event_valid, "latitude": 40.71, "longitude": -74.0}
    with pytest.raises(ValidationError):
        validate_against_schema("alert_event", bad)


def test_alert_event_rejects_extra_field(alert_event_valid):
    bad = {**alert_event_valid, "leak": "x"}
    with pytest.raises(ValidationError):
        validate_against_schema("alert_event", bad)


# ---------------- schema: alert_module ----------------

def test_alert_module_valid(alert_module_valid):
    validate_against_schema("alert_module", alert_module_valid)
    AlertModule(**alert_module_valid)


def test_alert_module_rejects_bad_activation(alert_module_valid):
    bad = {**alert_module_valid, "activation_status": "paused"}
    with pytest.raises(ValidationError):
        validate_against_schema("alert_module", bad)


# ---------------- VAL-001..010 ----------------

def test_val_pipeline_accepts_good_alert(alert_event_valid):
    res = validate_alert(alert_event_valid)
    assert res.valid
    assert res.violations == []


def test_val001_duplicate_id(alert_event_valid):
    res = validate_alert(alert_event_valid, known_alert_ids={alert_event_valid["alert_id"]})
    assert not res.valid
    assert any(v.rule_id == "VAL-001" for v in res.violations)


def test_val002_unknown_module(alert_event_valid):
    res = validate_alert({**alert_event_valid, "module_id": "NOPE"})
    assert any(v.rule_id == "VAL-002" and v.rejecting for v in res.violations)


def test_val003_start_after_end(alert_event_valid):
    res = validate_alert({**alert_event_valid, "start_at": "2026-06-28T00:00:00-04:00",
                          "end_at": "2026-06-27T00:00:00-04:00"})
    assert any(v.rule_id == "VAL-003" for v in res.violations)
    assert not res.valid


def test_val004_sourceless(alert_event_valid):
    res = validate_alert({**alert_event_valid, "source_ref": "", "source_hash": None})
    assert any(v.rule_id == "VAL-004" for v in res.violations)


def test_val005_one_sided_coords(alert_event_valid):
    res = validate_alert({**alert_event_valid, "latitude": 18.3, "longitude": None})
    assert any(v.rule_id == "VAL-005" for v in res.violations)


def test_val006_exact_needs_source_backed_coords(alert_event_valid):
    res = validate_alert({**alert_event_valid, "coord_confidence": "exact",
                          "latitude": None, "longitude": None})
    assert any(v.rule_id == "VAL-006" for v in res.violations)


def test_val007_bad_event_type(alert_event_valid):
    res = validate_alert({**alert_event_valid, "event_type": "fireworks"})
    assert any(v.rule_id == "VAL-007" for v in res.violations)


def test_val008_is_advisory_not_rejecting(alert_event_valid):
    res = validate_alert({**alert_event_valid, "status": "active", "asset_id": None})
    v008 = [v for v in res.violations if v.rule_id == "VAL-008"]
    assert v008 and not v008[0].rejecting
    assert res.valid  # advisory only


def test_val009_low_confidence_must_have_gap(alert_event_valid):
    res = validate_alert({**alert_event_valid, "confidence": 20, "gap_status": "none"})
    assert any(v.rule_id == "VAL-009" for v in res.violations)


def test_val010_unsupported_covert_flag(alert_event_valid):
    res = validate_alert({**alert_event_valid, "covert_flags": ["secret_cabal"]})
    assert any(v.rule_id == "VAL-010" and v.rejecting for v in res.violations)


def test_covert_vocab_is_structural():
    assert "intake_dependency" in COVERT_FLAG_VOCAB
    assert "secret_cabal" not in COVERT_FLAG_VOCAB


# ---------------- seed integrity ----------------

def test_seed_events_load_and_validate():
    # data/alert_events.jsonl now holds the hand-authored seeds PLUS data-driven
    # alerts generated by scripts/build_water_alerts.py (SDWIS/reservoir). Assert
    # every row is a schema-valid AlertEvent and the seed floor is intact.
    events = load_events()
    assert len(events) >= 10
    for e in events:
        AlertEvent(**e)


def test_seed_events_pass_val_pipeline():
    results = validate_alerts(load_events())
    rejected = [r.as_dict() for r in results if not r.valid]
    assert rejected == [], rejected


def test_seed_modules_and_active_set():
    modules = load_modules()
    assert len(modules) == 10
    active = {m["module_id"] for m in modules if m["activation_status"] == "active"}
    assert active >= ACTIVE_MODULES  # the 5 sector modules are active


def test_seed_edges_and_gaps_load():
    # Edges now include the water↔power `energizes` crosswalk
    # (scripts/build_water_power_crosswalk.py) on top of the seed edges.
    assert len(load_edges()) >= 5
    assert len(load_gaps()) == 5


# ---------------- SQLite build + GeoJSON ----------------

def test_build_sqlite_in_memory_loads_all_tables():
    conn = build_sqlite(":memory:")
    try:
        counts = {
            t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("alert_modules", "alert_events", "alert_dependency_edges", "alert_gaps")
        }
    finally:
        conn.close()
    # Row counts track the data files: 10 modules / 5 gaps are fixed; events and
    # edges grow with the data-driven alert + crosswalk layers.
    assert counts["alert_modules"] == 10
    assert counts["alert_gaps"] == 5
    assert counts["alert_events"] == len(load_events())
    assert counts["alert_dependency_edges"] == len(load_edges())
    assert counts["alert_events"] >= 10
    assert counts["alert_dependency_edges"] >= 5


def test_sqlite_enforces_coord_pairing():
    import sqlite3
    conn = build_sqlite(":memory:")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO alert_events (alert_id, module_id, event_type, status, "
                "source_title, source_ref, start_at, asset_name, municipalities, "
                "coord_confidence, severity, confidence, gap_status, review_status, "
                "evidence_tier, latitude, longitude) VALUES "
                "('AYL_ALR_20260627_x_001','HYDRO_OPS','maintenance','draft','t','seed://x',"
                "'2026-06-27T00:00:00-04:00','x','[]','unknown',1,10,'minor','blocked','T4',18.3,NULL)"
            )
    finally:
        conn.close()


def test_geojson_projection_skips_null_coords():
    events = load_events()
    geo = events_to_geojson(events)
    assert geo["type"] == "FeatureCollection"
    # Every projected feature carries coordinates; events with null coords are
    # skipped. With data-driven alerts, many events now geolocate (SDWIS via
    # municipio centroid), so assert the invariant rather than a fixed count.
    assert len(geo["features"]) == sum(
        1 for e in events if e.get("latitude") is not None and e.get("longitude") is not None
    )
    assert all(f["geometry"]["coordinates"] for f in geo["features"])
    # The Carraízo HYDRO_OPS seed is still present with its coordinates.
    carraizo = [f for f in geo["features"] if f["geometry"]["coordinates"] == [-66.01, 18.344]]
    assert len(carraizo) == 1
    assert carraizo[0]["properties"]["module_id"] == "HYDRO_OPS"
