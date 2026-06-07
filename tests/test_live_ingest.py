"""Live-network tests for FRS + FEMA. Gated by EPA_LIVE_TESTS=1 to keep CI offline.

Set EPA_LIVE_TESTS=1 to run these:
    EPA_LIVE_TESTS=1 pytest tests/test_live_ingest.py -v
"""

from __future__ import annotations

import os

import pytest

from aguayluz.ingest.fema import parse_fema_response
from aguayluz.ingest.fema_client import fetch_all_pa_records
from aguayluz.ingest.frs import parse_frs_response
from aguayluz.ingest.frs_client import fetch_facilities

LIVE_FLAG = os.environ.get("EPA_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(not LIVE_FLAG, reason="set EPA_LIVE_TESTS=1 to run")


@pytest.mark.live
def test_live_frs_bayamon_returns_records():
    """Bayamón is a known-populated PR city in FRS."""
    envelope = fetch_facilities(state_abbr="PR", city_name="BAYAMON")
    facilities = envelope.get("Results", {}).get("FRSFacility", [])
    assert len(facilities) > 0, "FRS returned no records for Bayamón"
    seeds = parse_frs_response(envelope)
    assert len(seeds) == len(facilities)


@pytest.mark.live
def test_live_fema_pr_water_control_returns_records():
    """PR has hurricane María recovery → many damage-code-F records."""
    envelope = fetch_all_pa_records(state_abbr="PR", damage_codes=["F"], max_records=10)
    records = envelope.get("PublicAssistanceFundedProjectsDetails", [])
    assert len(records) > 0
    seeds = parse_fema_response(envelope)
    # At least one should classify as utility (damage code F).
    utility = [s for s in seeds if s.is_utility]
    assert len(utility) > 0
