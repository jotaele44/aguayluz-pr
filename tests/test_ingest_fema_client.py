"""Tests for the FEMA OpenFEMA HTTP client (mocked)."""

from __future__ import annotations

import pytest

from aguayluz.ingest.fema_client import (
    FEMAClientError,
    _build_filter,
    fetch_all_pa_records,
    fetch_public_assistance,
)

# ---------- filter builder ----------


def test_filter_state_only():
    assert _build_filter(state_abbr="PR") == "stateAbbreviation eq 'PR'"


def test_filter_single_damage_code():
    f = _build_filter(state_abbr="PR", damage_codes=["F"])
    assert f == "stateAbbreviation eq 'PR' and damageCategoryCode eq 'F'"


def test_filter_multiple_damage_codes_uses_or_group():
    f = _build_filter(state_abbr="PR", damage_codes=["D", "F"])
    assert f == (
        "stateAbbreviation eq 'PR' and "
        "(damageCategoryCode eq 'D' or damageCategoryCode eq 'F')"
    )


def test_filter_includes_disaster_number():
    f = _build_filter(state_abbr="PR", damage_codes=["F"], disaster_number=4339)
    assert "disasterNumber eq 4339" in f


# ---------- fetch_public_assistance ----------


def test_fetch_constructs_odata_query(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        json={"PublicAssistanceFundedProjectsDetails": []},
        status_code=200,
    )
    fetch_public_assistance(state_abbr="PR", damage_codes=["F"], top=50, skip=10)
    req = httpx_mock.get_request()
    assert req.url.params["$filter"] == "stateAbbreviation eq 'PR' and damageCategoryCode eq 'F'"
    assert req.url.params["$top"] == "50"
    assert req.url.params["$skip"] == "10"


def test_fetch_metadata_flag_toggles_param(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        json={"PublicAssistanceFundedProjectsDetails": []},
        status_code=200,
    )
    fetch_public_assistance(state_abbr="PR", include_metadata=False)
    req = httpx_mock.get_request()
    assert "$metadata" not in dict(req.url.params)


def test_fetch_retries_5xx(httpx_mock):
    httpx_mock.add_response(method="GET", status_code=502, text="boom")
    httpx_mock.add_response(method="GET", json={"PublicAssistanceFundedProjectsDetails": []}, status_code=200)
    result = fetch_public_assistance(state_abbr="PR", max_retries=2)
    assert "PublicAssistanceFundedProjectsDetails" in result


def test_fetch_raises_on_4xx(httpx_mock):
    httpx_mock.add_response(method="GET", status_code=400, text="bad query")
    with pytest.raises(FEMAClientError, match="HTTP 400"):
        fetch_public_assistance(state_abbr="PR")


# ---------- fetch_all_pa_records (pagination) ----------


def test_fetch_all_paginates_until_empty(httpx_mock):
    # First page: 100 records. Second page: 25 records (smaller than top → done).
    page1 = {"PublicAssistanceFundedProjectsDetails": [{"i": i} for i in range(100)]}
    page2 = {"PublicAssistanceFundedProjectsDetails": [{"i": i + 100} for i in range(25)]}
    httpx_mock.add_response(method="GET", json=page1, status_code=200)
    httpx_mock.add_response(method="GET", json=page2, status_code=200)
    result = fetch_all_pa_records(state_abbr="PR", max_records=500)
    assert len(result["PublicAssistanceFundedProjectsDetails"]) == 125
    assert result["metadata"]["count"] == 125


def test_fetch_all_honors_max_records(httpx_mock):
    page = {"PublicAssistanceFundedProjectsDetails": [{"i": i} for i in range(100)]}
    httpx_mock.add_response(method="GET", json=page, status_code=200)
    result = fetch_all_pa_records(state_abbr="PR", max_records=50, page_size=100)
    # Only one page requested, capped at 50.
    assert len(result["PublicAssistanceFundedProjectsDetails"]) == 50


def test_fetch_all_handles_immediate_empty(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        json={"PublicAssistanceFundedProjectsDetails": []},
        status_code=200,
    )
    result = fetch_all_pa_records(state_abbr="PR")
    assert result["PublicAssistanceFundedProjectsDetails"] == []
    assert result["metadata"]["count"] == 0
