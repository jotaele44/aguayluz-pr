"""USGS river rate-of-rise adapter (aguayluz.hazard_adapters.river_rise).

Fixtures in ``tests/fixtures/usgs_river_rise/``:

* ``continuous_00065.json`` / ``continuous_00060.json`` — **real** captures of the USGS
  Water Data OGC API ``continuous`` collection for the PR bbox, 2026-11-26T18:03Z to
  2026-11-27T00:03Z, trimmed to six sites: four stream gauges (50043000, 50055000,
  50059050, 50111315 — the last one has no NWPS gauge), one reservoir
  (182827067040500) and one irrigation canal (50093110).
* ``fiona_2022_50043000_00065.json`` — **real** 5-minute stage for Río de la Plata at
  Proyecto La Plata (NWPS AIBP4), 2022-09-18 06:00Z–2022-09-19 00:00Z, Hurricane Fiona.
  The stage crossed NWPS action stage (15 ft) at 16:15Z.
* ``nwps_gauge_state.jsonl`` — **real** rows from ``data/nwps_gauge_state.jsonl`` for the
  three NWPS gauges bound to those sites (thresholds, last observed stage).

Everything built with :func:`feat` below is **constructed** to pin one behaviour.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aguayluz.hazard_adapters import river_rise as rr
from aguayluz.hazard_plane import RecordStatus

FIX = Path(__file__).parent / "fixtures" / "usgs_river_rise"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
CAPTURE_END = datetime(2026, 11, 27, 0, 3, 36, tzinfo=timezone.utc)
STREAM = {"50043000", "50055000", "50059050", "50111315"}


def feat(site: str, minutes: float, value, pcode: str = "00065", **props) -> dict:
    when = T0 + timedelta(minutes=minutes)
    return {"type": "Feature", "properties": {
        "monitoring_location_id": f"USGS-{site}", "parameter_code": pcode,
        "statistic_id": props.pop("statistic_id", "00011"),
        "time": when.isoformat(), "value": value if value is None else str(value),
        "unit_of_measure": "ft" if pcode == "00065" else "ft^3/s",
        "approval_status": "Provisional", "qualifier": props.pop("qualifier", None),
        "time_series_id": props.pop("time_series_id", f"ts-{site}-{pcode}"), **props}}


def series(values: list[float], step: int = 15, start: float = 0) -> list[rr.Observation]:
    return [rr.Observation(T0 + timedelta(minutes=start + i * step), float(v))
            for i, v in enumerate(values)]


def settings(**over) -> dict:
    return rr.site_settings({"defaults": rr._deep_merge(rr.DEFAULTS, over), "sites": {}}, "X")


def nwps_rows() -> dict[str, dict]:
    rows = [json.loads(line) for line in (FIX / "nwps_gauge_state.jsonl").read_text().splitlines()]
    return {r["usgs_id"]: r for r in rows}


# ------------------------------------------------------------------ collect


def test_real_capture_arithmetic_closes_and_non_stream_sites_are_excluded():
    docs = [json.loads((FIX / f"continuous_{p}.json").read_text()) for p in ("00065", "00060")]
    got = rr.collect(rr.features_of(docs), STREAM)
    assert got.source == got.retained + got.excluded + got.unresolved
    assert got.outcomes["excluded:not_a_stream_site"] > 0  # reservoir + canal
    assert set(got.stage) == STREAM
    stage = got.stage["50043000"]
    assert [o.time for o in stage] == sorted(o.time for o in stage)
    assert all(o.approval == "Provisional" for o in stage)


def test_every_feature_lands_in_exactly_one_outcome():
    features = [
        feat("1", 0, 1.0),
        feat("1", 0, 1.1),                                   # duplicate timestamp
        feat("1", 15, None),                                 # no value, no reason
        feat("1", 30, None, pcode="00060", qualifier=["RATINGDEV"]),  # withheld by USGS
        feat("1", 45, "abc"),                                # unparseable
        feat("1", 60, 2.0, statistic_id="00003"),            # daily mean
        feat("1", 75, 2.0, pcode="00010"),                   # temperature
        feat("1", 90, 2.0, qualifier=["Eqp"]),               # equipment malfunction
        feat("2", 0, 1.0),                                   # not a stream site
        {"type": "Feature", "properties": {"time": T0.isoformat()}},  # no site
        "garbage",
    ]
    got = rr.collect(features, {"1"})
    assert got.source == len(features)
    assert got.retained + got.excluded + got.unresolved == len(features)
    assert got.outcomes == {
        "retained": 1, "excluded:duplicate_time": 1, "unresolved:missing_value": 1,
        "excluded:value_withheld": 1, "unresolved:unparseable_value": 1,
        "excluded:statistic_00003": 1, "excluded:parameter_00010": 1,
        "excluded:qualifier": 1, "excluded:not_a_stream_site": 1,
        "unresolved:missing_site": 1, "unresolved:not_a_feature": 1,
    }


def test_secondary_time_series_is_excluded_and_counted():
    features = [feat("1", i * 15, 1.0, time_series_id="main") for i in range(4)]
    features += [feat("1", i * 15, 5.0, time_series_id="backup") for i in range(2)]
    got = rr.collect(features, None)
    assert [o.value for o in got.stage["1"]] == [1.0] * 4
    assert got.outcomes["excluded:secondary_time_series"] == 2
    assert got.time_series_ids["1"]["00065"] == "main"
    assert got.retained + got.excluded == 6


def test_interior_spike_is_removed_but_a_sustained_step_is_kept():
    spiky = series([1.0, 1.0, 4.0, 1.05, 1.1])
    kept, removed = rr.remove_spikes(spiky, 1.0)
    assert removed == 1 and [o.value for o in kept] == [1.0, 1.0, 1.05, 1.1]
    step = series([1.0, 1.0, 4.0, 4.1, 4.2])
    assert rr.remove_spikes(step, 1.0)[1] == 0


def test_approval_status_reads_the_live_field_and_the_old_name():
    assert rr.approval_status({"approval_status": "Approved"}) == "Approved"
    assert rr.approval_status({"approvals_status": ["Approved"]}) == "Approved"
    assert rr.approval_status({}) == "Provisional"


# ------------------------------------------------------------------ metrics


def test_value_lookup_is_by_time_over_mixed_steps_and_gaps():
    obs = [rr.Observation(T0 + timedelta(minutes=m), float(m)) for m in (0, 5, 10, 25, 40, 95)]
    tol = timedelta(minutes=10)
    assert rr.value_at(obs, T0 + timedelta(minutes=30), tol) == 25.0
    assert rr.value_at(obs, T0 + timedelta(minutes=60), tol) is None  # in the 40→95 gap
    assert rr.value_at(obs, T0 + timedelta(minutes=95), tol) == 95.0


def test_rising_since_is_the_last_base_level_reading_before_the_climb():
    obs = series([3.0, 2.0, 1.5, 1.55, 2.5, 4.0])
    assert rr.rising_since(obs, 0.1) == T0 + timedelta(minutes=45)  # 1.55 is within 0.1 of 1.5
    flat = series([3.0] * 8 + [3.6, 4.2])
    assert rr.rising_since(flat, 0.1) == T0 + timedelta(minutes=15 * 7)


def analyse(values, *, step=15, nwps=None, discharge=None, now_after=0, **over):
    stage = series(values, step)
    now = stage[-1].time + timedelta(minutes=now_after)
    q = series(discharge, step) if discharge else []
    return rr.analyse_site(rr.SiteContext("X", nwps=nwps), stage, q, now, settings(**over))


def test_rise_metrics_and_classes():
    flat = analyse([5.0] * 13)
    assert flat["rise_class"] == "NONE" and flat["data_state"] == rr.OK
    assert flat["metrics"]["rise_1h_ft"] == 0.0

    elevated = analyse([5.0] * 9 + [5.3, 5.6, 5.8, 6.1])  # +1.1 ft in 1 h
    assert elevated["rise_class"] == "ELEVATED_RISE"
    assert elevated["metrics"]["rise_1h_ft"] == pytest.approx(1.1)

    rapid = analyse([5.0] * 9 + [5.5, 6.0, 6.6, 7.2])  # +2.2 ft in 1 h
    assert rapid["rise_class"] == "RAPID_RISE"

    flash = analyse([5.0] * 9 + [6.0, 7.0, 8.0, 9.5])  # +4.5 ft in 1 h, 1.5 in 15 min
    assert flash["rise_class"] == "FLASH_RISE"
    assert flash["metrics"]["rate_ft_per_h"] > 4
    assert any("rise_1h_ft" in r for r in flash["class_reasons"])


def test_three_hour_rise_alone_can_grade_rapid():
    slow = analyse([5.0 + 0.36 * i for i in range(13)])  # 4.3 ft over 3 h, 1.4 ft per hour
    assert slow["metrics"]["rise_3h_ft"] == pytest.approx(4.32)
    assert slow["rise_class"] == "RAPID_RISE"


def test_unconfirmed_jump_in_the_newest_reading_is_capped_at_elevated():
    jump = analyse([5.0] * 12 + [7.5])
    assert jump["data_state"] == rr.PENDING
    assert jump["rise_class"] == "ELEVATED_RISE"
    assert "capped" in jump["class_reasons"][-1]
    confirmed = analyse([5.0] * 10 + [5.6, 6.2, 8.0])  # already rising before the jump
    assert confirmed["data_state"] == rr.OK
    assert confirmed["rise_class"] == "FLASH_RISE"


def test_discharge_ratio_needs_a_base_flow_floor_and_a_stage_rise_at_flash():
    tiny = analyse([5.0] * 13, discharge=[1.0] * 12 + [60.0])
    assert tiny["metrics"]["q_ratio"] is None  # 1 cfs base flow: ratio is meaningless
    rated = analyse([5.0] * 13, discharge=[50.0] * 12 + [400.0])
    assert rated["metrics"]["q_ratio"] == 8.0
    # q_ratio ≥ 5 with no stage rise is only ELEVATED: discharge is rated from stage.
    assert rated["rise_class"] == "ELEVATED_RISE"


def test_headroom_scales_thresholds_within_the_clamp():
    s = settings()
    base = rr.applied_thresholds(s, None)
    assert base["RAPID_RISE"]["rise_1h_ft"] == 2.0
    # 0.3 × 30 ft / 2 ft = 4.5 → clamped to 3×.
    assert rr.applied_thresholds(s, 30.0)["RAPID_RISE"]["rise_1h_ft"] == 6.0
    # Just below action stage: never below the absolute default.
    assert rr.applied_thresholds(s, 0.5)["RAPID_RISE"]["rise_1h_ft"] == 2.0
    # Ratios are dimensionless: headroom scales stage rises only.
    assert rr.applied_thresholds(s, 30.0)["ELEVATED_RISE"]["q_ratio"] == 3.0


def test_site_override_scale_and_suppression():
    config = rr.load_thresholds()
    config["sites"] = {"S": {"scale": 2.0, "suppress": True, "note": "dam release"}}
    s = rr.site_settings(config, "S")
    assert s["scale"] == 2.0 and s["suppress"] and s["note"] == "dam release"
    assert rr.applied_thresholds(s, None)["RAPID_RISE"]["rise_1h_ft"] == 4.0
    stage = series([5.0] * 9 + [6.0, 7.0, 8.0, 9.5])
    row = rr.analyse_site(rr.SiteContext("S"), stage, [], stage[-1].time, s)
    assert row["data_state"] == rr.SUPPRESSED and row["rise_class"] == "NONE"


def test_projection_requires_matching_datum():
    values = [5.0] * 9 + [5.5, 6.0, 6.6, 7.2]
    last = T0 + timedelta(minutes=15 * 12)
    nwps = {"lid": "XXXP4", "observed": {"stage": 7.2, "valid_time": last.isoformat()},
            "thresholds": {"action": {"stage": 8.0}, "minor": {"stage": 9.0}}}
    row = analyse(values, nwps=nwps)
    assert row["datum_check"] == "PASS"
    assert 0 < row["projection"]["to_action_minutes"] < 60
    assert row["projection"]["to_minor_minutes"] is not None
    assert rr.minor_within(row, settings())

    shifted = dict(nwps, observed={"stage": 107.2, "valid_time": last.isoformat()})
    row = analyse(values, nwps=shifted)
    assert row["datum_check"] == "FAIL"
    assert row["projection"]["to_action_minutes"] is None
    assert row["thresholds_applied"]["RAPID_RISE"]["rise_1h_ft"] == 2.0  # no headroom scaling

    later = dict(nwps, observed={"stage": 7.2, "valid_time": (last + timedelta(hours=3)).isoformat()})
    assert analyse(values, nwps=later)["datum_check"] == "NO_COMMON_TIME"
    assert analyse(values)["datum_check"] == "NO_NWPS"


def test_already_above_threshold_projects_zero():
    last = T0 + timedelta(minutes=15 * 12)
    nwps = {"observed": {"stage": 9.5, "valid_time": last.isoformat()},
            "thresholds": {"action": {"stage": 8.0}}}
    row = analyse([9.5] * 13, nwps=nwps)
    assert row["projection"]["to_action_minutes"] == 0.0


def test_stale_and_insufficient_data_states():
    stale = analyse([5.0] * 9 + [6.0, 7.0, 8.0, 9.5], now_after=200)
    assert stale["data_state"] == rr.STALE
    assert stale["latency_minutes"] == 200.0
    sparse = analyse([5.0, 9.0], step=60)
    assert sparse["data_state"] == rr.INSUFFICIENT and sparse["rise_class"] == "NONE"
    empty = rr.analyse_site(rr.SiteContext("X"), [], [], T0, settings())
    assert empty["data_state"] == rr.NO_STAGE and empty["series"] is None


def test_series_is_a_fixed_grid_ending_at_the_latest_reading():
    row = analyse([float(i) for i in range(30)])
    grid = row["series"]["stage_ft"]
    assert len(grid) == 25 and grid[-1] == 29.0 and grid[0] == 5.0
    assert row["series"]["end"] == rr.iso(T0 + timedelta(minutes=15 * 29))


def test_live_capture_reads_quiet_for_every_site():
    docs = [json.loads((FIX / f"continuous_{p}.json").read_text()) for p in ("00065", "00060")]
    got = rr.collect(rr.features_of(docs), STREAM)
    config = rr.load_thresholds()
    nwps = nwps_rows()
    rows = {site: rr.analyse_site(rr.SiteContext(site, nwps=nwps.get(site)), got.stage[site],
                                  got.discharge.get(site, []), CAPTURE_END,
                                  rr.site_settings(config, site))
            for site in got.stage}
    assert all(r["rise_class"] == "NONE" for r in rows.values())
    assert rows["50043000"]["datum_check"] == "PASS"
    assert rows["50111315"]["datum_check"] == "NO_NWPS"
    assert 30 <= rows["50043000"]["latency_minutes"] <= 120


def test_fiona_rise_is_graded_before_the_action_crossing_is_visible():
    doc = json.loads((FIX / "fiona_2022_50043000_00065.json").read_text())
    stage = rr.collect(rr.features_of([doc]), None).stage["50043000"]
    config = rr.load_thresholds()
    crossing = datetime(2022, 9, 18, 16, 15, tzinfo=timezone.utc)
    first: dict[str, datetime] = {}
    t = datetime(2022, 9, 18, 12, 0, tzinfo=timezone.utc)
    while t < datetime(2022, 9, 18, 19, 0, tzinfo=timezone.utc):
        visible = [o for o in stage if o.time <= t - timedelta(minutes=45)]
        row = rr.analyse_site(rr.SiteContext("50043000"), visible, [], t,
                              rr.site_settings(config, "50043000"))
        first.setdefault(row["rise_class"], t)
        t += timedelta(minutes=15)
    # The crossing becomes visible 45 min after it happens; the rise is graded first.
    assert first["RAPID_RISE"] < crossing + timedelta(minutes=45)
    assert "FLASH_RISE" in first


# ------------------------------------------------------------------ episodes


def row_for(cls: str, minutes: float, *, rise_1h: float = 2.5, state: str = rr.OK,
            onset_minutes: float | None = None, to_minor: float | None = None) -> dict:
    latest = T0 + timedelta(minutes=minutes)
    return {
        "site_no": "X", "data_state": state, "rise_class": cls,
        "metrics": {"rise_1h_ft": rise_1h},
        "latest": {"time": rr.iso(latest)},
        "rising_since": rr.iso(T0 + timedelta(minutes=onset_minutes if onset_minutes is not None else minutes - 60)),
        "projection": {"to_minor_minutes": to_minor},
        "datum_check": "PASS" if to_minor is not None else "NO_NWPS",
    }


def record_from(step: rr.EpisodeStep, row: dict, head=None):
    return rr.episode_record(step.event_id, step.material, row, rr.SiteContext("X"), "HYDROMET:m:1",
                             supersedes=head.record_id if head else None,
                             observed_to=rr.parse_time(row["latest"]["time"]),
                             effective_to=step.end)


def test_episode_lifecycle_open_escalate_quiet_close():
    s, classes = settings(), ("RAPID_RISE", "FLASH_RISE")
    assert rr.advance_episode(None, row_for("ELEVATED_RISE", 0), T0, s, classes).action == "none"

    opened = rr.advance_episode(None, row_for("RAPID_RISE", 60, onset_minutes=0), T0, s, classes)
    assert opened.action == "open"
    assert opened.event_id == "USGS_RISE:X:20260901T1200Z"
    head = record_from(opened, row_for("RAPID_RISE", 60))
    assert head.status == RecordStatus.ACTIVE

    # Same peak, different current class: no revision.
    assert rr.advance_episode(head, row_for("RAPID_RISE", 75), T0, s, classes).action == "none"
    up = rr.advance_episode(head, row_for("FLASH_RISE", 90), T0, s, classes)
    assert up.action == "revise" and up.material["peak_class"] == "FLASH_RISE"
    head = record_from(up, row_for("FLASH_RISE", 90), head)

    # Falling back to RAPID keeps the peak; nothing new to record.
    assert rr.advance_episode(head, row_for("RAPID_RISE", 105), T0, s, classes).action == "none"

    quiet = rr.advance_episode(head, row_for("NONE", 120, rise_1h=0.0), T0, s, classes)
    assert quiet.action == "none" and quiet.quiet_since == rr.iso(T0 + timedelta(minutes=120))
    # A new rise resets the quiet clock.
    again = rr.advance_episode(head, row_for("RAPID_RISE", 150), T0, s, classes,
                               previous_quiet_since=quiet.quiet_since)
    assert again.quiet_since is None
    quiet = rr.advance_episode(head, row_for("NONE", 180, rise_1h=0.05), T0, s, classes)
    still = rr.advance_episode(head, row_for("NONE", 240, rise_1h=0.0), T0, s, classes,
                               previous_quiet_since=quiet.quiet_since)
    assert still.action == "none"
    closed = rr.advance_episode(head, row_for("NONE", 270, rise_1h=0.0), T0, s, classes,
                                previous_quiet_since=quiet.quiet_since)
    assert closed.action == "close" and closed.closed_reason == "receded"
    assert closed.end == T0 + timedelta(minutes=180)
    final = record_from(closed, row_for("NONE", 270), head)
    assert final.status == RecordStatus.TERMINATED
    assert final.effective_to == T0 + timedelta(minutes=180)
    assert final.supersedes_record_id == head.record_id


def test_minor_stage_flag_is_sticky_and_makes_a_revision():
    s, classes = settings(), ("RAPID_RISE", "FLASH_RISE")
    opened = rr.advance_episode(None, row_for("RAPID_RISE", 60), T0, s, classes)
    head = record_from(opened, row_for("RAPID_RISE", 60))
    flagged = rr.advance_episode(head, row_for("RAPID_RISE", 75, to_minor=40), T0, s, classes)
    assert flagged.action == "revise" and flagged.material["minor_within_60m"]
    head = record_from(flagged, row_for("RAPID_RISE", 75, to_minor=40), head)
    assert rr.advance_episode(head, row_for("RAPID_RISE", 90), T0, s, classes).action == "none"


def test_stale_data_holds_then_force_closes_after_a_day():
    s, classes = settings(), ("RAPID_RISE", "FLASH_RISE")
    opened = rr.advance_episode(None, row_for("RAPID_RISE", 60), T0, s, classes)
    head = record_from(opened, row_for("RAPID_RISE", 60))
    stale_row = row_for("RAPID_RISE", 60, state=rr.STALE)
    hold = rr.advance_episode(head, stale_row, T0 + timedelta(hours=5), s, classes)
    assert hold.action == "hold"
    assert rr.advance_episode(head, None, T0 + timedelta(hours=5), s, classes).action == "hold"
    gone = rr.advance_episode(head, None, T0 + timedelta(hours=26), s, classes)
    assert gone.action == "close" and gone.closed_reason == "stale"
    assert gone.end == T0 + timedelta(minutes=60)


def test_new_rise_after_a_closed_episode_gets_a_later_onset():
    s, classes = settings(), ("RAPID_RISE", "FLASH_RISE")
    after = T0 + timedelta(minutes=200)
    step = rr.advance_episode(None, row_for("RAPID_RISE", 260, onset_minutes=0), T0, s, classes,
                              not_before=after)
    assert step.event_id == rr.canonical_event_id("X", after)


def test_record_ids_are_stable_and_chain_dependent():
    material = rr.material_state("X", rr.iso(T0), "RAPID_RISE", False, False)
    a = rr.stable_record_id("E", material, None)
    assert a == rr.stable_record_id("E", material, None)
    assert a != rr.stable_record_id("E", material, "E:REV:prev")
    assert a.startswith("E:REV:")


def test_thresholds_config_loads_and_rejects_a_foreign_schema(tmp_path):
    config = rr.load_thresholds()
    assert config["schema_version"] == "aguayluz.river-rise-thresholds/v1"
    assert rr.promotion_classes(config) == ("RAPID_RISE", "FLASH_RISE")
    assert config["defaults"]["closure"]["quiet_minutes"] == 90
    bad = tmp_path / "t.json"
    bad.write_text(json.dumps({"schema_version": "other"}))
    with pytest.raises(ValueError):
        rr.load_thresholds(bad)
    assert rr.load_thresholds(tmp_path / "missing.json")["defaults"]["spike_ft"] == 1.0
