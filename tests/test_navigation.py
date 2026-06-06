"""Tests for `aguayluz.waters.navigation`.

Both layers are tested offline:
  - WATERS tracing uses pytest-httpx against the v4 upstreamdownstream fixture.
  - pynhd is stubbed via `set_nldi_probe(...)` and an injectable StreamCat
    fetcher — no real network calls, no `pynhd.NLDI` dependency at test time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aguayluz.waters import WatersClient
from aguayluz.waters.navigation import (
    FlowlineSummary,
    enrich_streamcat,
    nldi_has_pr,
    set_nldi_probe,
    trace_downstream,
    trace_upstream,
)

FIXTURES = Path(__file__).parent / "fixtures" / "waters"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _reset_nldi_probe():
    """Reset the probe + cache around every test so state never leaks."""
    yield
    set_nldi_probe(lambda _comid: False)  # ensure cache is cleared
    nldi_has_pr.cache_clear()


# ---------------- WATERS-primary tracing ----------------


def test_trace_downstream_projects_features(httpx_mock):
    payload = _load("upstreamdownstream_vpu21.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        flowlines = trace_downstream(c, comid=21000100, distance_km=10.0)
    assert len(flowlines) == 2
    assert all(isinstance(f, FlowlineSummary) for f in flowlines)
    first = flowlines[0]
    assert first.comid == 21000100
    assert first.reachcode == "21010002000001"
    assert first.nhdplus_region == "21"
    assert first.gnis_name == "Lago La Plata"
    assert first.length_km == 1.32


def test_trace_downstream_uses_dd_direction_by_default(httpx_mock):
    payload = _load("upstreamdownstream_vpu21.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        trace_downstream(c, comid=21000100, distance_km=10.0)
    req = httpx_mock.get_request()
    assert req.url.params["pnavigationid"] == "DD"


def test_trace_downstream_with_tributaries_uses_dm(httpx_mock):
    payload = _load("upstreamdownstream_vpu21.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        trace_downstream(c, comid=21000100, distance_km=10.0, include_tributaries=True)
    req = httpx_mock.get_request()
    assert req.url.params["pnavigationid"] == "DM"


def test_trace_upstream_uses_ut_with_tributaries(httpx_mock):
    payload = _load("upstreamdownstream_vpu21.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        trace_upstream(c, comid=21000100, distance_km=5.0)
    req = httpx_mock.get_request()
    assert req.url.params["pnavigationid"] == "UT"


def test_trace_upstream_main_only_uses_um(httpx_mock):
    payload = _load("upstreamdownstream_vpu21.json")
    httpx_mock.add_response(method="GET", json=payload, status_code=200)
    with WatersClient(api_key="k") as c:
        trace_upstream(c, comid=21000100, distance_km=5.0, include_tributaries=False)
    req = httpx_mock.get_request()
    assert req.url.params["pnavigationid"] == "UM"


def test_trace_handles_empty_feature_collection(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        json={"network_flowlines": {"type": "FeatureCollection", "features": []}, "catchments": None},
        status_code=200,
    )
    with WatersClient(api_key="k") as c:
        flowlines = trace_downstream(c, comid=99999, distance_km=1.0)
    assert flowlines == []


# ---------------- pynhd enrichment + PR coverage probe ----------------


def test_probe_caches_after_first_call():
    calls: list[int] = []

    def probe(comid: int) -> bool:
        calls.append(comid)
        return True

    set_nldi_probe(probe)
    assert nldi_has_pr() is True
    assert nldi_has_pr() is True
    assert nldi_has_pr() is True
    assert calls == [21000100], "probe should be called exactly once and cached"


def test_enrich_returns_partial_when_probe_fails():
    set_nldi_probe(lambda _c: False)
    result = enrich_streamcat(21000100, "MeanFlow", nhdplus_region="21")
    assert result.value is None
    assert result.attribute_coverage == "partial"
    assert "no PR coverage" in (result.reason or "")


def test_enrich_returns_partial_for_vpu21_unavailable_metric_even_when_probe_ok():
    set_nldi_probe(lambda _c: True)
    # NLCD-prefixed metric is documented unavailable for VPU 21.
    result = enrich_streamcat(21000100, "NLCD2019Pct_Forest", nhdplus_region="21")
    assert result.value is None
    assert result.attribute_coverage == "partial"
    assert "VPU 21" in (result.reason or "")


def test_enrich_returns_full_when_probe_ok_and_metric_available():
    set_nldi_probe(lambda _c: True)
    captured: list[tuple[int, str]] = []

    def fake_fetch(comid: int, metric: str) -> float:
        captured.append((comid, metric))
        return 0.42

    result = enrich_streamcat(
        21000100, "SafeNonNLCDMetric", nhdplus_region="21", fetch_fn=fake_fetch
    )
    assert result.value == 0.42
    assert result.attribute_coverage == "full"
    assert captured == [(21000100, "SafeNonNLCDMetric")]


def test_enrich_returns_partial_when_fetcher_raises():
    set_nldi_probe(lambda _c: True)

    def boom(_c: int, _m: str) -> float:
        raise RuntimeError("StreamCat unavailable")

    result = enrich_streamcat(
        21000100, "AnyMetric", nhdplus_region="02", fetch_fn=boom
    )
    assert result.value is None
    assert result.attribute_coverage == "partial"
    assert "StreamCat" in (result.reason or "")


def test_enrich_mainland_vpu_does_not_trigger_vpu21_block():
    """A mainland (non-VPU-21) NLCD metric should NOT be blocked."""
    set_nldi_probe(lambda _c: True)

    def fake_fetch(_c: int, _m: str) -> float:
        return 1.0

    result = enrich_streamcat(
        12345678, "NLCD2019Pct_Forest", nhdplus_region="02", fetch_fn=fake_fetch
    )
    assert result.attribute_coverage == "full"
    assert result.value == 1.0
