from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from research.mycelial.app import app
from research.mycelial.lifecycle import (
    EnvironmentalSnapshot,
    LifecycleObservation,
    MediaEvidence,
    MushroomSite,
    StateTransition,
    SurveySession,
    append_media,
    append_observation,
    append_site,
    append_snapshot,
    append_survey,
    append_transition,
    initialize_lifecycle_tables,
    safe_site_view,
)
from research.mycelial.importers import REQUIRED_SURVEY_FIELDS, account_rows, read_jsonl, read_survey_csv

NOW = "2026-08-02T18:00:00Z"


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    initialize_lifecycle_tables(conn)
    return conn


def seed(conn: sqlite3.Connection) -> None:
    append_site(conn, MushroomSite("site-1", "Plot One", "Adjuntas", 18.2, -66.7, "exact", True), NOW)
    append_survey(conn, SurveySession("survey-1", "site-1", NOW, NOW, "observer", "fixed_plot", 15, 10, "detected"), NOW)
    append_observation(conn, LifecycleObservation("obs-1", "survey-1", "site-1", NOW, "fruiting_confirmed", "verified", count=3), NOW)


def test_append_only_site_survey_observation_and_media() -> None:
    conn = database()
    seed(conn)
    append_media(conn, MediaEvidence("media-1", "obs-1", "photo", "a" * 64, NOW), NOW)
    append_snapshot(conn, EnvironmentalSnapshot("snap-1", "site-1", NOW, "weather", rainfall_72h_mm=22, relative_humidity_pct=90), NOW)
    assert conn.execute("select count(*) from mushroom_sites").fetchone()[0] == 1
    assert conn.execute("select count(*) from lifecycle_observations").fetchone()[0] == 1
    assert conn.execute("select count(*) from media_evidence").fetchone()[0] == 1


def test_sensitive_site_coordinates_are_withheld() -> None:
    site = MushroomSite("site-1", "Plot", None, 18.2, -66.7, "exact", True)
    public = safe_site_view(site)
    assert public["latitude"] is None
    assert public["longitude"] is None
    assert safe_site_view(site, True)["latitude"] == 18.2


def test_negative_survey_requires_completed_effort() -> None:
    conn = database()
    append_site(conn, MushroomSite("site-1", "Plot", None, None, None, "unknown"), NOW)
    with pytest.raises(ValueError, match="negative_survey_requires_end_time"):
        append_survey(conn, SurveySession("survey-1", "site-1", NOW, None, "observer", "transect", 10, None, "not_detected"), NOW)


def test_invalid_transition_is_rejected() -> None:
    conn = database()
    seed(conn)
    with pytest.raises(ValueError, match="invalid_lifecycle_transition"):
        append_transition(conn, StateTransition("tx-1", "site-1", "peak", "environmental_priming", NOW, "obs-1", "high", "invalid reversal"), NOW)


def test_valid_transition_is_append_only() -> None:
    conn = database()
    seed(conn)
    append_transition(conn, StateTransition("tx-1", "site-1", "fruiting_confirmed", "expansion", NOW, "obs-1", "high", "count increased"), NOW)
    assert conn.execute("select to_state from lifecycle_transitions").fetchone()[0] == "expansion"


def test_importers_are_bounded_and_accounted() -> None:
    rows = read_jsonl(b'{"site_id":"s1"}\n')
    assert rows == [{"site_id": "s1"}]
    csv_rows = read_survey_csv(b"survey_id,site_id,started_at,observer,method,effort_minutes,detection_status\na,s,2026-08-02T00:00:00Z,o,fixed_plot,5,detected\n")
    assert csv_rows[0]["effort_minutes"] == 5.0
    assert account_rows(csv_rows, REQUIRED_SURVEY_FIELDS) == {"seen": 1, "accepted": 1, "rejected": 0}


def test_lifecycle_console_and_prediction_boundary() -> None:
    client = TestClient(app)
    status = client.get("/research/mycelial/lifecycle/status")
    assert status.status_code == 200
    assert status.json()["phase"] == 1
    console = client.get("/research/mycelial/lifecycle/console")
    assert console.status_code == 200
    assert "no location prediction" in console.text.lower()
    prediction = client.get("/research/mycelial/lifecycle/prediction/location_ranking")
    assert prediction.status_code == 503
    assert prediction.json()["status"] == "model_not_calibrated"
