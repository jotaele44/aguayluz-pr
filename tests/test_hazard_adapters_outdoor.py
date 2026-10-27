"""Pure parsers behind the outdoor-condition ingests."""
from datetime import date, datetime, timezone

import pytest

from aguayluz.hazard_adapters import airnow, epa_uv, ndbc_buoys, nws_heat, nws_marine, nws_surf_zone


@pytest.mark.parametrize("line, expected", [
    ("PRZ001-182200-", (["PRZ001"], "182200")),
    ("PRZ001-005>007-182200-", (["PRZ001", "PRZ005", "PRZ006", "PRZ007"], "182200")),
    ("PRZ012-VIZ001-002-182200-", (["PRZ012", "VIZ001", "VIZ002"], "182200")),
    ("San Juan and Vicinity PR-", None),
    ("PRZ009>003-182200-", None),
])
def test_parse_ugc(line, expected):
    assert nws_surf_zone.parse_ugc(line) == expected


@pytest.mark.parametrize("text, expected", [
    ("Around 4 feet.", (4.0, 4.0)),
    ("3 to 5 feet.", (3.0, 5.0)),
    ("Surf height around 7 feet. Partly sunny.", (7.0, 7.0)),
    ("Surf height 6 to 9 feet, occasionally to 11 feet.", (6.0, 9.0)),
    ("Partly sunny.", (None, None)),
    (None, (None, None)),
])
def test_surf_height(text, expected):
    assert nws_surf_zone.surf_height_ft(text) == expected


def test_period_dates_walk_forward_from_the_issuance_day():
    sunday = date(2026, 10, 18)
    assert nws_surf_zone.period_dates(["TODAY", "MONDAY", "TUESDAY"], sunday) == [
        sunday, date(2026, 10, 19), date(2026, 10, 20)]
    # an afternoon product issued Saturday starts at Sunday
    assert nws_surf_zone.period_dates(["SUNDAY", "MONDAY"], date(2026, 10, 17)) == [
        sunday, date(2026, 10, 19)]
    assert nws_surf_zone.period_dates(["SOMEDAY"], sunday) == [None]


def test_unknown_risk_word_is_not_a_category():
    period = nws_surf_zone.Period(label="TODAY", detailed=True, rip_current_risk_raw="Elevated.")
    assert period.rip_current_risk is None
    period.rip_current_risk_raw = "High. "
    assert period.rip_current_risk == "HIGH"


def test_marine_event_key_follows_vtec_not_the_cap_id():
    props = {"id": "urn:a", "sent": "2026-10-18T08:00:00-04:00",
             "parameters": {"VTEC": ["/O.EXT.TJSJ.SC.Y.0042.000000T0000Z-261019T1000Z/"]}}
    assert nws_marine.event_key(props) == "TJSJ.SC.Y.0042.2026"
    assert nws_marine.event_key({"id": "urn:b", "parameters": {}}) == "urn:b"
    closing = {**props, "parameters": {"VTEC": ["/O.CAN.TJSJ.SC.Y.0042.000000T0000Z-261019T1000Z/"]}}
    assert nws_marine.material_state(closing, {"AMZ712"})["closed"] is True


def test_ndbc_header_is_required():
    with pytest.raises(ValueError):
        ndbc_buoys.parse_latest_obs("41053 18.4 -66.1 2026 10 18 17 00\n")


@pytest.mark.parametrize("index, category", [
    (None, None), (0, "LOW"), (2.9, "LOW"), (3, "MODERATE"), (7, "HIGH"), (10, "VERY_HIGH"), (11, "EXTREME"),
])
def test_uv_category(index, category):
    assert epa_uv.uv_category(index) == category


@pytest.mark.parametrize("value, band", [
    (None, None), (79.9, "BELOW_CAUTION"), (80, "CAUTION"), (95, "EXTREME_CAUTION"),
    (103, "DANGER"), (124.9, "DANGER"), (125, "EXTREME_DANGER"),
])
def test_heat_band(value, band):
    assert nws_heat.heat_band(value) == band


def test_grid_intervals_and_window_overlap():
    start, end = nws_heat.parse_interval("2026-10-18T10:00:00+00:00/P1DT6H")
    assert (end - start).total_seconds() == 30 * 3600
    assert nws_heat.parse_interval("2026-10-18T10:00:00+00:00/garbage") is None
    series = {"uom": "wmoUnit:degC", "values": [
        {"validTime": "2026-10-18T09:00:00+00:00/PT2H", "value": 30.0},   # overlaps the start
        {"validTime": "2026-10-18T20:00:00+00:00/PT1H", "value": 35.0},
        {"validTime": "2026-10-20T20:00:00+00:00/PT1H", "value": 50.0},   # outside 24 h
    ]}
    now = datetime(2026, 10, 18, 10, tzinfo=timezone.utc)
    value, at = nws_heat.window_max(series, now, now.replace(day=19))
    assert value == 35.0 and at == "2026-10-18T20:00:00Z"


def test_heat_rejects_a_non_celsius_unit():
    props = {"heatIndex": {"uom": "wmoUnit:degF",
                           "values": [{"validTime": "2026-10-18T12:00:00+00:00/PT1H", "value": 90}]}}
    with pytest.raises(ValueError):
        nws_heat.summarize(props, datetime(2026, 10, 18, 11, tzinfo=timezone.utc))


def test_airnow_local_hour_to_utc_and_unknown_zone():
    row = {"DateObserved": "2026-10-18 ", "HourObserved": 23, "LocalTimeZone": "AST"}
    assert airnow.observed_at(row) == datetime(2026, 10, 19, 3, tzinfo=timezone.utc)
    assert airnow.observed_at({**row, "LocalTimeZone": "XYZ"}) is None
    assert airnow.classify({"ReportingArea": "San Juan", "ParameterName": "O3", "AQI": -1,
                            "StateCode": "PR"}) == "unresolved:missing_aqi"
