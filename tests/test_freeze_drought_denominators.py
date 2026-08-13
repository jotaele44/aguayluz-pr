from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from scripts.freeze_drought_denominators import (
    assert_usdm_archive_closure,
    build_usgs_request_plan,
    expected_usdm_issue_dates,
    parse_ghcnd_pr_station_ids,
    parse_ghcnd_prcp_inventory,
)


def _station_line(station_id: str, state: str) -> str:
    # GHCN-D station fixed-width fields used by the parser: ID[0:11], STATE[38:40].
    chars = [" "] * 85
    chars[0:11] = station_id.ljust(11)[:11]
    chars[38:40] = state.ljust(2)[:2]
    return "".join(chars)


def _inventory_line(station_id: str, element: str, first: int, last: int) -> str:
    # GHCN-D inventory fields: ID[0:11], ELEMENT[31:35], FIRST[36:40], LAST[41:45].
    chars = [" "] * 50
    chars[0:11] = station_id.ljust(11)[:11]
    chars[31:35] = element.ljust(4)[:4]
    chars[36:40] = str(first)
    chars[41:45] = str(last)
    return "".join(chars)


def test_expected_usdm_denominator_is_exactly_156_tuesdays():
    dates = expected_usdm_issue_dates()
    assert len(dates) == 156
    assert dates[0] == date(2014, 1, 7)
    assert dates[-1] == date(2016, 12, 27)
    assert all(item.weekday() == 1 for item in dates)
    assert len(set(dates)) == len(dates)


def test_ncei_station_universe_filters_only_pr():
    text = "\n".join(
        [
            _station_line("USW00000001", "PR"),
            _station_line("USC00000002", "PR"),
            _station_line("USW00000003", "FL"),
        ]
    )
    assert parse_ghcnd_pr_station_ids(text) == {"USW00000001", "USC00000002"}


def test_ncei_inventory_requires_prcp_and_window_overlap():
    stations = {"USW00000001", "USC00000002", "USC00000004"}
    text = "\n".join(
        [
            _inventory_line("USW00000001", "PRCP", 1950, 2020),
            _inventory_line("USC00000002", "TMAX", 1950, 2020),
            _inventory_line("USC00000004", "PRCP", 1990, 2013),
            _inventory_line("USW00000009", "PRCP", 1950, 2020),
        ]
    )
    assert parse_ghcnd_prcp_inventory(text, stations) == {"USW00000001": (1950, 2020)}


def _write_usdm_zip(path: Path, dates: list[date]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for item in dates:
            archive.writestr(f"USDM_{item.strftime('%Y%m%d')}_M/USDM_{item.strftime('%Y%m%d')}.gml", "<gml/>")


def test_usdm_archive_closure_accepts_complete_partition(tmp_path: Path):
    expected = expected_usdm_issue_dates()
    paths = []
    for year in (2014, 2015, 2016):
        path = tmp_path / f"{year}.zip"
        _write_usdm_zip(path, [item for item in expected if item.year == year])
        paths.append(path)
    closure = assert_usdm_archive_closure(paths)
    assert closure == {
        "expected_week_count": 156,
        "observed_week_count": 156,
        "first_issue": "2014-01-07",
        "last_issue": "2016-12-27",
        "missing": [],
        "unexpected": [],
    }


def test_usdm_archive_closure_fails_closed_on_missing_week(tmp_path: Path):
    expected = expected_usdm_issue_dates()[1:]
    path = tmp_path / "incomplete.zip"
    _write_usdm_zip(path, expected)
    with pytest.raises(ValueError, match="USDM archive closure failed"):
        assert_usdm_archive_closure([path])


def test_usgs_plan_is_query_identity_not_certified_observations():
    plan = build_usgs_request_plan()
    assert {item["collection"] for item in plan} == {
        "time-series-metadata",
        "daily",
        "field-measurements",
    }
    assert all(item["certification"] == "query_identity_only" for item in plan)
    assert all("bbox=-67.95,17.7,-65.2,18.7" in item["url"] for item in plan)
    observation_requests = [item for item in plan if item["collection"] != "time-series-metadata"]
    assert all("2014-01-01" in item["url"] and "2016-12-31" in item["url"] for item in observation_requests)
