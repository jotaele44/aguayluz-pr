"""Unit tests for the WATERS HTTP client.

Covers auth resolution, retry/backoff on 429, env-var fallback, header vs
query auth modes, and JSON envelope passthrough. Live calls are NOT made —
all responses are mocked via pytest-httpx.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aguayluz.waters import AuthError, RateLimitExceeded, WatersClient, WatersServerError
from aguayluz.waters.client import DEFAULT_BASE_URL

FIXTURES = Path(__file__).parent / "fixtures" / "waters"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------- auth resolution ----------

def test_explicit_key_wins(monkeypatch):
    monkeypatch.setenv("EPA_WATERS_API_KEY", "env-eta")
    monkeypatch.setenv("API_DATA_GOV_KEY", "env-fallback")
    c = WatersClient(api_key="explicit")
    assert c.api_key == "explicit"


def test_epa_env_var_used(monkeypatch):
    monkeypatch.delenv("API_DATA_GOV_KEY", raising=False)
    monkeypatch.setenv("EPA_WATERS_API_KEY", "epa-key")
    c = WatersClient()
    assert c.api_key == "epa-key"


def test_api_data_gov_fallback(monkeypatch):
    monkeypatch.delenv("EPA_WATERS_API_KEY", raising=False)
    monkeypatch.setenv("API_DATA_GOV_KEY", "fallback-key")
    c = WatersClient()
    assert c.api_key == "fallback-key"


def test_missing_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("EPA_WATERS_API_KEY", raising=False)
    monkeypatch.delenv("API_DATA_GOV_KEY", raising=False)
    with pytest.raises(AuthError) as exc:
        WatersClient()
    assert "EPA_WATERS_API_KEY" in str(exc.value)


# ---------- base URL ----------

def test_default_base_url_is_waters_root_not_oas30():
    c = WatersClient(api_key="x")
    assert c.base_url == "https://api.epa.gov/waters"
    assert "/oas30" not in c.base_url, "/oas30 hosts the spec doc only; calls go to /v1, /v3, /v4."


# ---------- happy path GET ----------

def test_get_returns_parsed_json_envelope(httpx_mock):
    payload = _load("pointindexing_lago_la_plata.json")
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/pointindexing?pgeometry=POINT(-66.232+18.388)&output=JSON",
        json=payload,
        status_code=200,
    )
    with WatersClient(api_key="test") as c:
        resp = c.get("/v1/pointindexing", params={"pgeometry": "POINT(-66.232 18.388)"})
    assert "output" in resp
    assert resp["output"]["ary_flowlines"][0]["comid"] == 21000100
    assert resp["output"]["ary_flowlines"][0]["nhdplus_region"] == "21"


def test_auth_header_mode_sets_x_api_key(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/gnisnamelookup?pgnisname=La+Plata&output=JSON",
        json={"ok": True},
        status_code=200,
    )
    with WatersClient(api_key="hdr-key") as c:
        c.get("/v1/gnisnamelookup", params={"pgnisname": "La Plata"})
    req = httpx_mock.get_request()
    assert req.headers.get("X-Api-Key") == "hdr-key"
    assert "api_key" not in dict(req.url.params)


def test_auth_query_mode_sets_api_key_param(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/gnisnamelookup?pgnisname=Foo&output=JSON&api_key=q-key",
        json={"ok": True},
        status_code=200,
    )
    with WatersClient(api_key="q-key", auth_mode="query") as c:
        c.get("/v1/gnisnamelookup", params={"pgnisname": "Foo"})
    req = httpx_mock.get_request()
    assert req.url.params.get("api_key") == "q-key"
    assert "X-Api-Key" not in req.headers


def test_output_json_appended_automatically(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/gnisnamelookup?pgnisname=Foo&output=JSON",
        json={"ok": True},
        status_code=200,
    )
    with WatersClient(api_key="k") as c:
        c.get("/v1/gnisnamelookup", params={"pgnisname": "Foo"})
    req = httpx_mock.get_request()
    assert req.url.params["output"] == "JSON"


# ---------- error mapping ----------

def test_401_raises_auth_error(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/pointindexing?output=JSON",
        status_code=401,
        text="API_KEY_INVALID",
    )
    with WatersClient(api_key="bad") as c, pytest.raises(AuthError):
        c.get("/v1/pointindexing")


def test_500_raises_waters_server_error(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/pointindexing?output=JSON",
        status_code=502,
        text="Bad Gateway",
    )
    with WatersClient(api_key="k") as c, pytest.raises(WatersServerError) as exc:
        c.get("/v1/pointindexing")
    assert exc.value.status_code == 502


# ---------- 429 retry ----------

def test_429_retries_then_succeeds(httpx_mock):
    sleeps: list[float] = []
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/pointindexing?output=JSON",
        status_code=429,
        json={"error": "OVER_RATE_LIMIT"},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/pointindexing?output=JSON",
        status_code=429,
        json={"error": "OVER_RATE_LIMIT"},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/pointindexing?output=JSON",
        status_code=200,
        json={"ok": True},
    )
    with WatersClient(api_key="k", sleep_fn=sleeps.append) as c:
        resp = c.get("/v1/pointindexing")
    assert resp == {"ok": True}
    assert len(sleeps) == 2, "two backoff sleeps before the third attempt succeeds"


def test_429_honors_retry_after_header(httpx_mock):
    sleeps: list[float] = []
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/pointindexing?output=JSON",
        status_code=429,
        json={"error": "OVER_RATE_LIMIT"},
        headers={"Retry-After": "7"},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{DEFAULT_BASE_URL}/v1/pointindexing?output=JSON",
        status_code=200,
        json={"ok": True},
    )
    with WatersClient(api_key="k", sleep_fn=sleeps.append) as c:
        c.get("/v1/pointindexing")
    assert sleeps == [7.0]


def test_429_exhausted_raises_rate_limit_exceeded(httpx_mock):
    for _ in range(4):  # 1 initial + 3 retries
        httpx_mock.add_response(
            method="GET",
            url=f"{DEFAULT_BASE_URL}/v1/pointindexing?output=JSON",
            status_code=429,
            json={"error": "OVER_RATE_LIMIT"},
            headers={"Retry-After": "1"},
        )
    sleeps: list[float] = []
    with WatersClient(api_key="k", sleep_fn=sleeps.append) as c, pytest.raises(RateLimitExceeded) as exc:
        c.get("/v1/pointindexing")
    assert exc.value.attempts == 4
    assert len(sleeps) == 3  # three retries each slept


# ---------- endpoint wrappers ----------

def test_point_indexing_helper_calls_correct_path(httpx_mock):
    from aguayluz.waters.endpoints import point_indexing
    payload = _load("pointindexing_lago_la_plata.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        resp = point_indexing(c, lon=-66.232, lat=18.388, max_distance_km=5.0)
    req = httpx_mock.get_request()
    assert req.url.path.endswith("/v1/pointindexing")
    assert req.url.params["pgeometry"] == "POINT(-66.232 18.388)"
    assert req.url.params["ppointindexingmaxdist"] == "5.0"
    assert req.url.params["output"] == "JSON"
    assert resp["output"]["ary_flowlines"][0]["nhdplus_region"] == "21"


def test_first_flowline_helper():
    from aguayluz.waters.endpoints import first_flowline
    payload = _load("pointindexing_lago_la_plata.json")
    fl = first_flowline(payload)
    assert fl is not None
    assert fl["comid"] == 21000100
    assert fl["nhdplus_region"] == "21"
    assert first_flowline({"output": {"ary_flowlines": []}}) is None
    assert first_flowline({"output": {}}) is None
    assert first_flowline({}) is None


def test_upstream_downstream_helper(httpx_mock):
    from aguayluz.waters.endpoints import upstream_downstream
    payload = _load("upstreamdownstream_vpu21.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        resp = upstream_downstream(c, comid=21000100, distance_km=10.0, direction="DD")
    req = httpx_mock.get_request()
    assert req.url.path.endswith("/v4/upstreamdownstream")
    assert req.url.params["pstartcomid"] == "21000100"
    assert req.url.params["pnavigationid"] == "DD"
    assert "features" in resp["network_flowlines"]
    assert resp["network_flowlines"]["features"][0]["properties"]["nhdplus_region"] == "21"


def test_drainage_area_delineation_helper(httpx_mock):
    from aguayluz.waters.endpoints import drainage_area_delineation
    payload = _load("drainagearea_v3.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        resp = drainage_area_delineation(c, lon=-66.232, lat=18.388)
    req = httpx_mock.get_request()
    assert req.url.path.endswith("/v3/drainageareadelineation")
    assert req.url.params["pgeometry"] == "POINT(-66.232 18.388)"
    assert "Result_Delineated_Area" in resp


def test_gnis_name_lookup_helper(httpx_mock):
    from aguayluz.waters.endpoints import gnis_name_lookup
    payload = _load("gnis_pr.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        resp = gnis_name_lookup(c, name="La Plata", state="PR")
    req = httpx_mock.get_request()
    assert req.url.path.endswith("/v1/gnisnamelookup")
    assert req.url.params["pgnisname"] == "La Plata"
    assert req.url.params["pstate"] == "PR"
    assert resp["output"]["results"][0]["gnis_name"] == "Lago La Plata"
