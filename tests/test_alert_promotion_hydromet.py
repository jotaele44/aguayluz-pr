"""River-flood promoter over NWPS revision chains.

Revision chains are CONSTRUCTED with the adapter from the real QUEP4/AIBP4 captures,
editing only the observed flood category and valid time.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aguayluz.alert_promotion import GENERATED_MARKERS, build_all_alerts
from aguayluz.alert_promotion.hydromet import (
    FLOOD_SEVERITY,
    NWPS_FLOOD_MARKER,
    HydrometInputs,
    flood_episodes,
    river_flood_alerts,
)
from aguayluz.alert_validation import validate_alerts
from aguayluz.hazard_adapters import nwps_gauges as adapter
from aguayluz.impact import build_asset_index

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def _entry(lid):
    gauges = json.loads((FIXTURES / "nwps_pr_gauges_sample.json").read_text())["gauges"]
    return next(g for g in gauges if g["lid"] == lid)


def _detail(lid):
    return adapter.compact_detail(json.loads((FIXTURES / "nwps_gauge_details" / f"{lid}.json").read_text()))


def chain(lid, steps):
    """steps: [(category, hours_after_T0)] → revision chain, oldest first."""
    records, prev = [], None
    for category, hours in steps:
        entry = copy.deepcopy(_entry(lid))
        entry["status"]["observed"]["floodCategory"] = category
        entry["status"]["observed"]["validTime"] = (T0 + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        record = adapter.normalize(entry, _detail(lid), "HYDROMET:nwps_gauges:x",
                                   supersedes_record_id=prev.record_id if prev else None)
        records.append(record)
        prev = record
    return records


def state(lid, **overrides):
    entry, detail = _entry(lid), _detail(lid)
    row = {
        "lid": lid, "name": entry["name"], "latitude": entry["latitude"], "longitude": entry["longitude"],
        "pedts_observed": entry["pedts"]["observed"], "usgs_id": detail["usgsId"],
        "asset_id": f"USGS_{detail['usgsId']}", "municipio": detail["county"],
        "binding_evidence": "POINT_IN_POLYGON_WITH_ALIAS", "thresholds": adapter.flood_thresholds(detail),
        "threshold_stage_unit": "ft", "observed": {"valid_time": None},
    }
    row.update(overrides)
    return row


def test_episode_opens_peaks_and_closes():
    records = chain("AIBP4", [("no_flooding", 0), ("action", 1), ("moderate", 3), ("minor", 5), ("no_flooding", 8)])
    (episode,) = flood_episodes(records)
    assert episode.start == T0 + timedelta(hours=1)
    assert episode.end == T0 + timedelta(hours=8)
    assert episode.peak_category == "moderate"


def test_stale_observation_neither_opens_nor_closes():
    records = chain("AIBP4", [("minor", 0), ("obs_not_current", 2), ("minor", 3)])
    (episode,) = flood_episodes(records)
    assert episode.end is None
    assert flood_episodes(chain("AIBP4", [("obs_not_current", 0)])) == []


def test_two_floods_are_two_episodes():
    records = chain("AIBP4", [("action", 0), ("no_flooding", 2), ("minor", 10), ("no_flooding", 12)])
    assert [e.peak_category for e in flood_episodes(records)] == ["action", "minor"]


def test_open_episode_alert_is_active_and_scoped():
    records = chain("QUEP4", [("no_flooding", 0), ("minor", 2)])
    now = T0 + timedelta(hours=3)
    st = state("QUEP4", observed={"valid_time": (T0 + timedelta(hours=2)).isoformat()})
    index = build_asset_index([{"asset_id": "WTR1", "asset_type": "water", "municipality": "Quebradillas"}])
    (alert,) = river_flood_alerts(HydrometInputs(records, [st], now), None, index)
    assert NWPS_FLOOD_MARKER in alert.alert_id and alert.alert_id.startswith("AYL_ALR_20261007_")
    assert alert.status == "active" and alert.end_at is None
    assert alert.severity == FLOOD_SEVERITY["minor"] == 3
    assert alert.municipalities == ["Quebradillas"]
    assert "USGS_50010800" in alert.linked_asset_ids and "WTR1" in alert.linked_asset_ids
    assert alert.coord_confidence == "exact"
    assert alert.review_status == "accepted"
    assert "reservoir pool" in alert.source_title
    assert all(r.valid for r in validate_alerts([alert.model_dump()]))


def test_closed_episode_reports_end_and_ages_out():
    records = chain("AIBP4", [("major", 0), ("no_flooding", 4)])
    st = state("AIBP4")
    (alert,) = river_flood_alerts(HydrometInputs(records, [st], T0 + timedelta(days=1)))
    assert alert.status == "closed" and alert.end_at == "2026-10-07T16:00:00Z"
    assert alert.severity == 5
    assert river_flood_alerts(HydrometInputs(records, [st], T0 + timedelta(days=45))) == []


def test_stale_open_episode_goes_to_review():
    records = chain("AIBP4", [("moderate", 0)])
    st = state("AIBP4", observed={"valid_time": T0.isoformat()})
    (alert,) = river_flood_alerts(HydrometInputs(records, [st], T0 + timedelta(hours=12)))
    assert alert.review_status == "needs_review"
    assert "stale" in alert.validation_notes


def test_unresolved_binding_names_both_candidates_for_review():
    records = chain("AIBP4", [("action", 0)])
    st = state("AIBP4", municipio=None, county_raw="Caguas", candidate_municipio="Gurabo",
               binding_evidence="UNRESOLVED")
    (alert,) = river_flood_alerts(HydrometInputs(records, [st], T0))
    assert alert.municipalities == ["Caguas", "Gurabo"]
    assert alert.review_status == "needs_review"


def test_no_state_row_falls_back_without_coordinates():
    records = chain("AIBP4", [("minor", 0)])
    (alert,) = river_flood_alerts(HydrometInputs(records, [], T0))
    assert alert.coord_confidence == "unknown" and alert.latitude is None
    assert alert.municipalities == ["(unscoped)"]


def test_registered_with_the_engine_and_marker():
    assert NWPS_FLOOD_MARKER in GENERATED_MARKERS
    records = chain("QUEP4", [("minor", 0)])
    alerts = build_all_alerts([], [], {}, [], hydromet=HydrometInputs(records, [state("QUEP4")], T0))
    assert any(NWPS_FLOOD_MARKER in a.alert_id for a in alerts)
    assert not any(NWPS_FLOOD_MARKER in a.alert_id for a in build_all_alerts([], [], {}, []))
    assert river_flood_alerts(None) == []
