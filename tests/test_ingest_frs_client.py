"""Tests for the EPA FRS HTTP client (mocked)."""

from __future__ import annotations

import json

import httpx
import pytest

from aguayluz.ingest.frs_client import (
    FRS_BASE_URL,
    FRSClientError,
    _parse_frs_response,
    _repair_frs_json,
    fetch_all_pr_facilities,
    fetch_facilities,
    normalize_city_name,
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


# ---------- M22: malformed-JSON resilience ----------


def test_repair_doubles_stray_backslash_before_letter():
    # PONCE real-world: `"PRPBA\SYNERGY GROUP"` — \S is not a valid JSON escape.
    bad = r'{"name":"PRPBA\SYNERGY GROUP"}'
    repaired = _repair_frs_json(bad)
    parsed = json.loads(repaired)
    assert parsed["name"] == r"PRPBA\SYNERGY GROUP"


def test_repair_preserves_valid_escapes():
    # All standard JSON escapes survive the repair pass unchanged.
    good = r'{"a":"line1\nline2","b":"tab\there","c":"quote\"inside","d":"slash\\back","e":"ABC"}'
    repaired = _repair_frs_json(good)
    assert repaired == good
    parsed = json.loads(repaired)
    assert parsed["a"] == "line1\nline2"
    assert parsed["e"] == "ABC"   # A → 'A'


def test_repair_handles_caguas_pattern():
    # CAGUAS real-world: `"V\BLANCA SHOP.CNTR"` — \B is not a valid JSON escape.
    bad = r'{"LocationAddress":"V\BLANCA SHOP.CNTR PR#1 KM39.9"}'
    parsed = json.loads(_repair_frs_json(bad))
    assert parsed["LocationAddress"] == r"V\BLANCA SHOP.CNTR PR#1 KM39.9"


def test_parse_handles_literal_control_char_via_strict_false():
    # MAYAGUEZ real-world: literal TAB (0x09) embedded in a string value.
    response = httpx.Response(200, content=b'{"FacilityName":"\tCENTER FOR ENERGY"}')
    parsed = _parse_frs_response(response)
    assert "CENTER FOR ENERGY" in parsed["FacilityName"]


def test_parse_strict_first_falls_back_on_decode_error():
    # If strict parse succeeds we don't run the repair pass at all.
    clean = httpx.Response(200, content=b'{"ok":true}')
    assert _parse_frs_response(clean) == {"ok": True}


def test_fetch_returns_repaired_response_on_bad_escape(httpx_mock):
    bad_json_bytes = rb'{"Results":{"FRSFacility":[{"RegistryId":"X1","FacilityName":"PRPBA\SYNERGY"}]}}'
    httpx_mock.add_response(method="GET", content=bad_json_bytes, status_code=200,
                            headers={"Content-Type": "application/json"})
    result = fetch_facilities(state_abbr="PR", city_name="PONCE")
    assert result["Results"]["FRSFacility"][0]["FacilityName"] == r"PRPBA\SYNERGY"


def test_fetch_all_continues_after_per_city_decode_failure(httpx_mock):
    # First city: returns un-recoverable content (not JSON at all).
    # Second city: returns valid JSON.
    httpx_mock.add_response(method="GET", content=b"<html>EPA temporary failure</html>",
                            status_code=200)
    httpx_mock.add_response(
        method="GET",
        json={"Results": {"FRSFacility": [
            {"RegistryId": "X2", "FacilityName": "OK FACILITY"},
        ]}},
        status_code=200,
    )
    result = fetch_all_pr_facilities(cities=["PONCE", "BAYAMON"])
    assert len(result) == 1
    assert result[0]["RegistryId"] == "X2"


# ---------- M22: city-name normalization ----------


def test_normalize_city_name_translates_underscores():
    assert normalize_city_name("SAN_JUAN") == "SAN JUAN"


def test_normalize_city_name_uppercases_and_strips():
    assert normalize_city_name("  San_Juan  ") == "SAN JUAN"


def test_normalize_city_name_handles_no_underscore():
    assert normalize_city_name("BAYAMON") == "BAYAMON"
