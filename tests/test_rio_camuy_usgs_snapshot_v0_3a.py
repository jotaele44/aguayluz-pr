from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("rio_camuy_usgs_snapshot_v0_3a", REPO / "tools" / "rio_camuy_usgs_snapshot.py")
assert _SPEC and _SPEC.loader
snapshot = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = snapshot
_SPEC.loader.exec_module(snapshot)


def _empty(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"type": "FeatureCollection", "features": [], "links": []}, request=request)


def test_monitoring_locations_uses_id_query_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _empty(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot.fetch_collection(client, "monitoring-locations", site="50014800")

    assert len(seen) == 1
    assert seen[0].url.params.get("id") == "USGS-50014800"
    assert "monitoring_location_id" not in seen[0].url.params


def test_time_series_metadata_retains_monitoring_location_id_query_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _empty(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshot.fetch_collection(client, "time-series-metadata", site="50014600")

    assert len(seen) == 1
    assert seen[0].url.params.get("monitoring_location_id") == "USGS-50014600"
    assert "id" not in seen[0].url.params
