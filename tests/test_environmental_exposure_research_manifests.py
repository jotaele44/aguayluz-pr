from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "research/environmental_exposure/dorado_groundwater_benchmark.v1.json"
DENOMINATOR = ROOT / "research/environmental_exposure/source_denominator_progress.v1.json"


def test_dorado_benchmark_remains_negative_attribution_control():
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    site = data["authoritative_site"]

    assert data["classification"] == "NEGATIVE_ATTRIBUTION_CONTROL"
    assert data["production_promotion_allowed"] is False
    assert site["source_attribution_state"] == "UNKNOWN"
    assert data["promotion_gate"]["current_state"] == "BLOCKED_BY_UNKNOWN_SOURCE"

    for candidate in data["discovery_candidates"]:
        assert candidate["causal_state"] == "DISCOVERY_CANDIDATE"
        assert candidate["adjudication_state"] == "CANDIDATE_NOT_IDENTITY"
        assert candidate["attributed_to_dorado_plume"] is False


def test_environmental_source_denominator_cannot_claim_closure_yet():
    data = json.loads(DENOMINATOR.read_text(encoding="utf-8"))

    assert data["overall_state"] == "OPEN"
    assert data["completeness_claimed"] is False
    assert all(family["state"] != "EXHAUSTED" for family in data["families"])
    assert any(family.get("open_subscopes") for family in data["families"])
