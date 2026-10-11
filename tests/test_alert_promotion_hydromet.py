"""River-flood and heavy-rain promoters over the hydromet plane.

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
    HEAVY_RAIN_FOLLOW_UP,
    HEAVY_RAIN_MARKER,
    HEAVY_RAIN_MEAN_IN,
    NWPS_FLOOD_MARKER,
    HydrometInputs,
    flood_episodes,
    heavy_rain_alerts,
    river_flood_alerts,
)
from aguayluz.alert_validation import validate_alerts
from aguayluz.hazard_adapters import nwps_gauges as adapter
from aguayluz.hazard_adapters import stage_iv_qpe as stage_iv
from aguayluz.impact import build_asset_index
from aguayluz.water_alerts import load_geo

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


# ---------------------------------------------------------------- heavy rain (Stage IV)
# Records are CONSTRUCTED with the Stage IV adapter; only the rainfall values differ from
# the real 2026-10-09 Aguada summary.

RAIN_END = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
RAIN_MAN = "HYDROMET:stage_iv_pr:" + "b" * 32
GEO_FILE = Path(__file__).resolve().parent.parent / "data" / "geo" / "pr_municipios.json"


def rain(municipio="Aguada", geoid="72003", *, mean=1.064, peak=1.606, window="1day",
         method="raster_cell_centres_in_polygon", end=RAIN_END, cells=9):
    values = stage_iv.zone_values(obs_mean=mean, obs_max=peak, normal_mean=0.28,
                                  cell_count=cells, normal_cell_count=cells)
    return stage_iv.normalize(values, RAIN_MAN, window=window, geoid=geoid, municipio=municipio,
                              data_time=end, source_file=f"nws_precip_{window}_{end:%Y%m%d}_pr.tif",
                              method=method)


def test_heavy_rain_thresholds_and_scope():
    records = [rain(), rain("Mayagüez", "72097", mean=3.2, peak=4.1), rain("Añasco", "72011", mean=2.0, peak=6.3)]
    geo = load_geo(json.loads(GEO_FILE.read_text())["municipios"])
    index = build_asset_index([{"asset_id": "WTR9", "asset_type": "water", "municipality": "Mayagüez"}])
    alerts = heavy_rain_alerts(HydrometInputs(records, [], RAIN_END + timedelta(hours=6)), geo, index)
    by_town = {a.municipalities[0]: a for a in alerts}
    assert set(by_town) == {"Mayagüez", "Añasco"}  # Aguada's 1.06 in stays below both
    assert by_town["Mayagüez"].severity == 2 and by_town["Añasco"].severity == 3
    may = by_town["Mayagüez"]
    assert may.alert_id == f"AYL_ALR_20261009{HEAVY_RAIN_MARKER}mayaguez"
    assert may.status == "active" and may.end_at is None
    assert may.start_at == "2026-10-08T12:00:00Z"
    assert may.coord_confidence == "approximate" and may.latitude is not None
    assert "WTR9" in may.linked_asset_ids and may.asset_id is None
    assert may.review_status == "accepted"
    assert f"mean ≥ {HEAVY_RAIN_MEAN_IN:g} in" in may.validation_notes
    assert "not an NWS warning" in may.validation_notes
    assert max(a.severity for a in alerts) < 4  # post-event analysis stays sub-critical
    assert all(r.valid for r in validate_alerts([a.model_dump() for a in alerts]))


def test_heavy_rain_closes_after_follow_up_and_ages_out():
    records = [rain(mean=3.5, peak=5.0)]
    closing = RAIN_END + HEAVY_RAIN_FOLLOW_UP + timedelta(minutes=1)
    (alert,) = heavy_rain_alerts(HydrometInputs(records, [], closing))
    assert alert.status == "closed"
    assert alert.end_at == "2026-10-12T12:00:00Z"
    assert heavy_rain_alerts(HydrometInputs(records, [], closing + timedelta(days=31))) == []


def test_heavy_rain_skips_longer_windows_and_unbound_zones_and_reviews_touching_cells():
    records = [
        rain(window="last7days", mean=9.0, peak=12.0),
        rain("Cataño", "72033", mean=None, peak=None, cells=0, method="no_raster_cell"),
        rain("Cataño", "72033", mean=3.4, peak=3.9, method="raster_cells_touching_polygon",
             end=RAIN_END - timedelta(days=1)),
    ]
    (alert,) = heavy_rain_alerts(HydrometInputs(records, [], RAIN_END))
    assert alert.municipalities == ["Cataño"] and alert.alert_id.startswith("AYL_ALR_20261008_")
    assert alert.review_status == "needs_review"
    assert "only touches" in alert.validation_notes


def test_heavy_rain_reads_only_the_current_revision():
    first = rain(mean=3.6, peak=4.0)
    values = stage_iv.zone_values(obs_mean=1.1, obs_max=1.7, normal_mean=0.28, cell_count=9, normal_cell_count=9)
    reprocessed = stage_iv.normalize(values, RAIN_MAN, window="1day", geoid="72003", municipio="Aguada",
                                     data_time=RAIN_END, source_file="f.tif",
                                     method="raster_cell_centres_in_polygon",
                                     supersedes_record_id=first.record_id)
    assert heavy_rain_alerts(HydrometInputs([first], [], RAIN_END))
    assert heavy_rain_alerts(HydrometInputs([first, reprocessed], [], RAIN_END)) == []


def test_heavy_rain_registered_with_the_engine_and_exporter():
    from scripts.federation_export import _GENERATED_ALERT_MARKERS

    assert HEAVY_RAIN_MARKER in GENERATED_MARKERS
    assert set(GENERATED_MARKERS) == set(_GENERATED_ALERT_MARKERS)
    alerts = build_all_alerts([], [], {}, [], hydromet=HydrometInputs([rain(mean=4.0)], [], RAIN_END))
    assert any(HEAVY_RAIN_MARKER in a.alert_id for a in alerts)
    assert heavy_rain_alerts(None) == []
