"""Tests for the EPA FRS HTTP client (mocked)."""

from __future__ import annotations

import httpx
import pytest

from aguayluz.ingest.frs_client import (
    FRS_BASE_URL,
    FRSClientError,
    fetch_all_pr_facilities,
    fetch_facilities,
)


def test_fetch_requires_secondary_filter():
    with pytest.raises(FRSClientError, match="requires at least one of"):
        fetch_facilities(state_abbr="PR")


def test_fetch_builds_query_params(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{FRS_BASE_URL}?state_abbr=PR&output=JSON&city_name=BAYAMON",
        json={"Results": {"FRSFacility": []}},
        status_code=200,
    )
    fetch_facilities(state_abbr="PR", city_name="BAYAMON")
    req = httpx_mock.get_request()
    assert req.url.params["state_abbr"] == "PR"
    assert req.url.params["city_name"] == "BAYAMON"
    assert req.url.params["output"] == "JSON"


def test_fetch_includes_program_acrnm(httpx_mock):
    httpx_mock.add_response(method="GET", json={"Results": {"FRSFacility": []}}, status_code=200)
    fetch_facilities(state_abbr="PR", city_name="BAYAMON", program_acrnm="NPDES")
    req = httpx_mock.get_request()
    assert req.url.params["pgm_sys_acrnm"] == "NPDES"


def test_fetch_returns_full_envelope(httpx_mock):
    payload = {
        "Results": {
            "FRSFacility": [
                {"RegistryId": "1", "FacilityName": "PRASA WTP", "Latitude83": "18.4",
                 "Longitude83": "-66.2", "CityName": "BAYAMON", "StateAbbr": "PR"},
            ]
        }
    }
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    result = fetch_facilities(state_abbr="PR", city_name="BAYAMON")
    assert result == payload


def test_fetch_retries_on_5xx(httpx_mock):
    httpx_mock.add_response(method="GET", status_code=503, text="Service Unavailable")
    httpx_mock.add_response(method="GET", status_code=503, text="Service Unavailable")
    httpx_mock.add_response(method="GET", json={"Results": {"FRSFacility": []}}, status_code=200)
    result = fetch_facilities(state_abbr="PR", city_name="BAYAMON", max_retries=2)
    assert result == {"Results": {"FRSFacility": []}}


def test_fetch_raises_after_exhausted_retries(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(method="GET", status_code=503, text="boom")
    with pytest.raises(FRSClientError, match="HTTP 503"):
        fetch_facilities(state_abbr="PR", city_name="BAYAMON", max_retries=2)


def test_fetch_raises_on_4xx_immediately(httpx_mock):
    httpx_mock.add_response(method="GET", status_code=400, text="Bad search")
    with pytest.raises(FRSClientError, match="HTTP 400"):
        fetch_facilities(state_abbr="PR", city_name="BAYAMON", max_retries=3)


def test_fetch_all_dedupes_by_registry_id(httpx_mock):
    # Same record returned by both city and county pulls.
    payload = {
        "Results": {
            "FRSFacility": [
                {"RegistryId": "X1", "FacilityName": "A", "CityName": "BAYAMON", "StateAbbr": "PR"},
            ]
        }
    }
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    result = fetch_all_pr_facilities(cities=["BAYAMON"], counties=["BAYAMON"])
    assert len(result) == 1
    assert result[0]["RegistryId"] == "X1"


def test_fetch_all_requires_some_filter():
    with pytest.raises(FRSClientError, match="at least one city or county"):
        fetch_all_pr_facilities()


def test_fetch_uses_injected_client(httpx_mock):
    httpx_mock.add_response(method="GET", json={"Results": {"FRSFacility": []}}, status_code=200)
    with httpx.Client() as client:
        result = fetch_facilities(state_abbr="PR", city_name="BAYAMON", client=client)
    assert result == {"Results": {"FRSFacility": []}}
