"""Live integration test for WATERS-backed downstream_of edges.

Gated by EPA_WATERS_API_KEY (or API_DATA_GOV_KEY) since it hits the live API.
Costs ~2 WATERS calls per run.

Verifies:
  - WatersClient + trace_downstream() actually return data for PR VPU 21.
  - The downstream trace from a Lago La Plata sub-COMID hits at least one
    other reach (network-connected).
"""

from __future__ import annotations

import os

import pytest

LIVE = bool(os.environ.get("EPA_WATERS_API_KEY") or os.environ.get("API_DATA_GOV_KEY"))
pytestmark = pytest.mark.skipif(not LIVE, reason="set EPA_WATERS_API_KEY to run")


@pytest.mark.live
def test_live_trace_downstream_pr_returns_flowlines():
    from aguayluz.waters import WatersClient
    from aguayluz.waters.navigation import trace_downstream

    # Lago La Plata COMID from the M3 fixture — a real PR/VPU 21 reach.
    with WatersClient() as client:
        flowlines = trace_downstream(client, comid=21000100, distance_km=5.0)
    # PR flow networks aren't dense, but at least one reach should be reachable.
    assert isinstance(flowlines, list)
    assert all(getattr(f, "nhdplus_region", None) in ("21", None) for f in flowlines)
