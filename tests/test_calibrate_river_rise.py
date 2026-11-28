"""scripts/calibrate_river_rise.py — replay and scoring, offline.

Uses the **real** Fiona fixture (``tests/fixtures/usgs_river_rise/fiona_2022_50043000_00065.json``,
Río de la Plata at Proyecto La Plata, NWPS AIBP4, action stage 15 ft crossed 2022-09-18
16:15Z). Everything else is **constructed** to pin one rule.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aguayluz.hazard_adapters import river_rise as rr

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "usgs_river_rise"


def _load():
    spec = importlib.util.spec_from_file_location(
        "calibrate_river_rise", REPO / "scripts" / "calibrate_river_rise.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["calibrate_river_rise"] = module
    spec.loader.exec_module(module)
    return module


cal = _load()
T0 = datetime(2026, 2, 1, tzinfo=timezone.utc)


def obs(values: list[float], step: int = 15, start: datetime = T0) -> list[rr.Observation]:
    return [rr.Observation(start + timedelta(minutes=step * i), float(v)) for i, v in enumerate(values)]


def fiona() -> rr.Collected:
    doc = json.loads((FIX / "fiona_2022_50043000_00065.json").read_text())
    return rr.collect(rr.features_of([doc]), None)


def contexts():
    found, stream, municipio = cal.load_contexts(FIX / "utility_assets.jsonl", FIX / "nwps_gauge_state.jsonl")
    return found, stream, municipio


def test_crossings_rearm_only_after_six_hours_below():
    series = obs([1] * 4 + [6] * 2 + [1] * 4 + [6] + [1] * 30 + [6])
    assert cal.crossings(series, 5.0) == [T0 + timedelta(minutes=60), T0 + timedelta(minutes=15 * 41)]


def test_crossing_kinds():
    limb = obs([1.0] * 8 + [1.5, 2.0, 2.5, 3.0, 6.0])
    assert cal.crossing_kind(limb, limb[-1].time, 1.0, 1.0) == "rising_limb"
    step = obs([1.0] * 12 + [6.0])
    assert cal.crossing_kind(step, step[-1].time, 1.0, 1.0) == "step"
    creep = obs([4.0 + 0.05 * i for i in range(30)])
    assert cal.crossing_kind(creep, creep[-1].time, 1.0, 1.0) == "gradual"
    assert cal.crossing_kind(obs([6.0]), T0, 1.0, 1.0) == "no_data"


def test_fiona_replay_flags_the_rising_limb_before_nwps_could_see_the_crossing():
    collected = fiona()
    found, _, _ = contexts()
    config = rr.load_thresholds()
    start = datetime(2022, 9, 18, 6, 0, tzinfo=timezone.utc)
    end = datetime(2022, 9, 19, 0, 0, tzinfo=timezone.utc)
    result = cal.replay(collected, start, end, config, found, {"50043000": "PASS"})
    assert result.episodes and result.episodes[0].peak_class == "FLASH_RISE"
    score = cal.score_storm(result, collected, found, {"50043000": "PASS"}, start,
                            latency=timedelta(minutes=45), window=timedelta(hours=6), config=config)
    first = score["detail"][0]
    assert first["crossing"] == "2022-09-18T16:15:00Z"
    assert first["kind"] == "rising_limb" and first["hit"] and first["ahead_of_nwps"]
    assert first["lead_over_nwps_minutes"] >= 15
    assert score["rising_limb_hit_rate"] == 1.0
    # Without a passing datum the NWPS thresholds are not trusted: nothing is labelled.
    assert cal.score_storm(result, collected, found, {}, start, latency=timedelta(minutes=45),
                           window=timedelta(hours=6), config=config)["crossings"] == 0


def test_quiet_window_rate_counts_episodes_per_site_month():
    flat = rr.Collected(stage={"S": obs([3.0] * 96 * 2)})
    config = rr.load_thresholds()
    result = cal.replay(flat, T0, T0 + timedelta(days=2), config, {}, {})
    score = cal.score_quiet(result)
    assert score["episodes"] == 0 and score["episodes_per_site_30d"] == 0.0
    assert score["site_days"] > 1.5

    noisy = rr.Collected(stage={"S": obs([3.0] * 40 + [3.0 + 0.6 * i for i in range(1, 9)] + [7.8] * 60)})
    result = cal.replay(noisy, T0, T0 + timedelta(hours=27), config, {}, {})
    assert cal.score_quiet(result)["episodes"] == 1


def test_flash_flood_warnings_are_parsed_and_scored_by_municipio():
    events = [
        {"event_id": "AYL_EVT_1", "status_text": "event='Flash Flood Warning' severity=Severe",
         "affected_area": "Aibonito, PR; Cayey, PR", "start_time": "2026-08-09T15:52:00-04:00",
         "end_time": "2026-08-09T18:00:00-04:00"},
        {"event_id": "AYL_EVT_2", "status_text": "event='Flood Advisory'", "affected_area": "Cayey, PR",
         "start_time": "2026-08-09T15:00:00-04:00"},
    ]
    (warning,) = cal.flash_flood_warnings(events)
    assert warning["municipios"] == ["Aibonito", "Cayey"]
    assert warning["start"] == datetime(2026, 8, 9, 19, 52, tzinfo=timezone.utc)
    result = cal.Replay(episodes=[cal.Episode("50043000", "E", warning["start"], warning["start"] + timedelta(minutes=30),
                                              "RAPID_RISE")], site_runs={"50043000": 10})
    score = cal.score_warning(result, warning, {"50043000": "Aibonito", "50055000": "Gurabo"})
    assert score["corroborated"] and score["stream_sites_in_area"] == ["50043000"]
    elsewhere = cal.score_warning(result, warning, {"50043000": "Gurabo"})
    assert not elsewhere["corroborated"] and elsewhere["stream_sites_in_area"] == []


def test_evaluate_requires_every_criterion():
    good = {"storm": {"rising_limb_crossings": 40, "rising_limb_hit_rate": 0.9},
            "quiet": {"episodes_per_site_30d": 0.1}}
    assert cal.evaluate(good) == (True, [])
    few = {"storm": {"rising_limb_crossings": 2, "rising_limb_hit_rate": 1.0}, "quiet": {"episodes_per_site_30d": 0.0}}
    assert not cal.evaluate(few)[0]
    noisy = {"storm": {"rising_limb_crossings": 40, "rising_limb_hit_rate": 0.9}, "quiet": {"episodes_per_site_30d": 2.0}}
    ok, reasons = cal.evaluate(noisy)
    assert not ok and "dry-season" in reasons[0]
    assert not cal.evaluate({"storm": good["storm"], "quiet": {}})[0]


def test_write_config_records_the_result_and_the_promotion_flag(tmp_path):
    target = tmp_path / "thresholds.json"
    shutil.copy(rr.THRESHOLDS_FILE, target)
    summary = [{"event": "fiona-2022", "kind": "storm", "start": "a", "end": "b", "stream_sites_with_stage": 3}]
    cal.write_config(target, summary, {"storm": {}}, True, [], 45.0)
    written = json.loads(target.read_text())
    assert written["calibration"]["status"] == "CALIBRATED_PASS"
    assert written["promotion"]["enabled"] is True
    assert written["calibration"]["events"][0]["event"] == "fiona-2022"
    cal.write_config(target, summary, {"storm": {}}, False, ["too few"], 45.0)
    written = json.loads(target.read_text())
    assert written["promotion"]["enabled"] is False and written["calibration"]["failed_criteria"] == ["too few"]
    assert rr.load_thresholds(target)["defaults"]["spike_ft"] == 1.0


def test_fetch_window_follows_next_links_and_caches(tmp_path, httpx_mock):
    page1 = {"type": "FeatureCollection", "features": [{"properties": {}}],
             "links": [{"rel": "next", "href": "https://api.waterdata.usgs.gov/next-page"}]}
    page2 = {"type": "FeatureCollection", "features": [{"properties": {}}], "links": []}
    httpx_mock.add_response(url=re.compile(r"https://api\.waterdata\.usgs\.gov/ogcapi/.*"), json=page1)
    httpx_mock.add_response(url="https://api.waterdata.usgs.gov/next-page", json=page2)
    start = datetime(2022, 9, 18, tzinfo=timezone.utc)
    docs = cal.fetch_window("00065", start, start + timedelta(hours=12), tmp_path)
    assert len(docs) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["00065_20220918_1.json", "00065_20220918_2.json"]
    again = cal.fetch_window("00065", start, start + timedelta(hours=12), tmp_path)  # cache only
    assert again == docs


def test_main_rejects_unknown_events(capsys):
    assert cal.main(["--event", "nope"]) == 2
    assert "unknown" in capsys.readouterr().err


@pytest.mark.parametrize("event_id", sorted(cal.EVENTS))
def test_fixed_windows_are_well_formed(event_id):
    spec = cal.EVENTS[event_id]
    assert spec["kind"] in {"storm", "quiet"}
    assert rr.parse_time(spec["start"]) < rr.parse_time(spec["end"])


def _iem(tmp_path, events):
    path = tmp_path / "vtec.json"
    path.write_text(json.dumps({"wfo": "TJSJ", "year": 2026, "events": events}))
    return path


def test_nws_products_label_dry_season_episodes_in_three_tiers(tmp_path):
    """CONSTRUCTED in the shape of the IEM vtec_events.py archive."""
    products = cal.load_nws_products([_iem(tmp_path, [
        {"phenomena": "FA", "significance": "Y", "ph_name": "Areal Flood", "sig_name": "Advisory",
         "locations": "Juana Diaz [PR], Villalba [PR]", "issue": "2026-02-14T18:30:00Z", "expire": "2026-02-14T20:30:00Z"},
        {"phenomena": "FF", "significance": "W", "ph_name": "Flash Flood", "sig_name": "Warning",
         "locations": "Carolina [PR], Loiza [PR]", "issue": "2026-02-02T05:00:00Z", "expire": "2026-02-02T08:00:00Z"},
        {"phenomena": "HT", "significance": "Y", "ph_name": "Heat", "sig_name": "Advisory",
         "locations": "Ponce [PR]", "issue": "2026-02-09T15:00:00Z", "expire": "2026-02-09T20:00:00Z"},
        {"phenomena": "FA", "significance": "Y", "locations": "St. Thomas [VI]",
         "issue": "2026-02-09T15:00:00Z", "expire": "2026-02-09T20:00:00Z"},
    ])])
    assert [p["label"] for p in products] == ["Areal Flood Advisory", "Flash Flood Warning"]

    def episode(site, onset):
        start = rr.parse_time(onset)
        return cal.Episode(site, "E", start, start + timedelta(minutes=45), "RAPID_RISE",
                           closed_run=start + timedelta(hours=3), end=start + timedelta(hours=2))

    result = cal.Replay(
        episodes=[episode("A", "2026-02-14T19:00:00Z"),   # same municipio, overlapping
                  episode("B", "2026-02-02T06:00:00Z"),   # rain elsewhere on the island
                  episode("C", "2026-02-09T16:00:00Z")],  # only a heat advisory and a VI product
        site_runs={"A": 96 * 10, "B": 96 * 10, "C": 96 * 10},
    )
    municipio_of = {"A": "Juana Díaz", "B": "Ponce", "C": "Ponce"}
    score = cal.score_quiet(result, municipio_of=municipio_of, products=products)
    tiers = {d["site"]: d["nws_tier"] for d in score["detail"]}
    assert tiers == {"A": "local", "B": "island", "C": "none"}
    assert (score["nws_local"], score["nws_island"], score["uncorroborated"]) == (1, 1, 1)
    assert score["uncorroborated_per_site_30d"] == round(1 / (30 / 30), 3)
    unlabelled = cal.score_quiet(result)
    assert unlabelled["labelled"] is False and "uncorroborated" not in unlabelled


def test_evaluate_prefers_the_uncorroborated_rate_when_labelled():
    storm = {"rising_limb_crossings": 40, "rising_limb_hit_rate": 0.9}
    labelled = {"storm": storm, "quiet": {"labelled": True, "episodes_per_site_30d": 2.0,
                                         "uncorroborated_per_site_30d": 0.3}}
    assert cal.evaluate(labelled) == (True, [])
    noisy = {"storm": storm, "quiet": {"labelled": True, "episodes_per_site_30d": 2.0,
                                      "uncorroborated_per_site_30d": 0.9}}
    ok, reasons = cal.evaluate(noisy)
    assert not ok and reasons[0].startswith("uncorroborated dry-season rate 0.9")
