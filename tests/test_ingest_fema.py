"""Tests for the FEMA OpenFEMA Public Assistance adapter + event pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from aguayluz.ingest import ingest_event_seeds
from aguayluz.ingest.fema import (
    UTILITY_DAMAGE_CODES,
    EventSeed,
    parse_fema_response,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fema"


def _load() -> dict:
    return json.loads((FIXTURES / "pr_public_assistance_sample.json").read_text(encoding="utf-8"))


# ---------- parse_fema_response ----------


def test_parse_fema_full_fixture():
    seeds = parse_fema_response(_load())
    assert len(seeds) == 5
    # Damage codes D and F are utilities; A (debris removal) is not.
    utility_seeds = [s for s in seeds if s.is_utility]
    non_utility = [s for s in seeds if not s.is_utility]
    assert len(utility_seeds) == 4
    assert len(non_utility) == 1
    assert non_utility[0].affected_area.startswith("Arecibo")


def test_event_id_pattern_matches_schema():
    seeds = parse_fema_response(_load())
    for s in seeds:
        # ServiceEvent schema requires pattern ^AYL_EVT_[0-9]{8}_[A-Za-z0-9_-]+$
        parts = s.seed_id.split("_", 3)
        assert parts[0] == "AYL"
        assert parts[1] == "EVT"
        assert len(parts[2]) == 8 and parts[2].isdigit()


def test_source_hash_uses_fema_hash_when_present():
    seeds = parse_fema_response(_load())
    # First record in fixture has hash "8baaf948268424feb8f7a07ee9da91cb9a0c8d94"
    yauco = next(s for s in seeds if "Yauco" in s.affected_area)
    assert yauco.source_hash == "8baaf948268424feb8f7a07ee9da91cb9a0c8d94"


def test_affected_area_combines_county_and_damage():
    seeds = parse_fema_response(_load())
    yauco = next(s for s in seeds if "Yauco" in s.affected_area)
    assert "Water Control Facilities" in yauco.affected_area
    assert ", PR" in yauco.affected_area


def test_iso_datetime_trimmed_to_z():
    seeds = parse_fema_response(_load())
    yauco = next(s for s in seeds if "Yauco" in s.affected_area)
    # Fixture has '2001-07-30T00:00:00.000Z' — sub-second precision stripped.
    assert yauco.start_time and yauco.start_time.endswith("Z")
    assert "." not in yauco.start_time


def test_utility_damage_codes_constant():
    assert {"D", "F"} == UTILITY_DAMAGE_CODES


def test_parse_fema_empty():
    assert parse_fema_response({}) == []
    assert parse_fema_response({"PublicAssistanceFundedProjectsDetails": []}) == []


# ---------- ingest_event_seeds (pipeline) ----------


def test_pipeline_drops_non_utility():
    seeds = parse_fema_response(_load())
    result = ingest_event_seeds(seeds)
    # 4 utility seeds → 4 events; debris removal → skipped
    assert len(result.events) == 4
    assert len(result.skipped) == 1
    assert result.review_items == []
    assert result.coverage_pct == 80.0


def test_pipeline_records_t2_evidence_tier():
    seeds = parse_fema_response(_load())
    result = ingest_event_seeds(seeds)
    assert all(ev["evidence_tier"] == "T2" for ev in result.events)


def test_pipeline_default_review_status_needs_review():
    seeds = parse_fema_response(_load())
    result = ingest_event_seeds(seeds)
    assert all(ev["review_status"] == "needs_review" for ev in result.events)


def test_pipeline_routes_validation_failures_to_review():
    bad_seed = EventSeed(
        seed_id="badid",   # doesn't match AYL_EVT_<8digit>_... pattern
        event_type="outage",
        affected_area="X",
        source_ref="https://example.gov",
        is_utility=True,
    )
    result = ingest_event_seeds([bad_seed])
    assert result.events == []
    assert len(result.review_items) == 1
    assert "validation failed" in result.review_items[0]["reason"]


def test_pipeline_can_process_non_utility_when_flag_disabled():
    seeds = parse_fema_response(_load())
    result = ingest_event_seeds(seeds, skip_non_utility=False)
    assert len(result.events) == 5
    assert result.skipped == []


def test_pipeline_uses_linked_asset_ids():
    seeds = parse_fema_response(_load())
    # Pre-wire one link
    target = next(s for s in seeds if "Toa Alta" in s.affected_area)
    links = {target.seed_id: ["AYL_AST_FRS_999"]}
    result = ingest_event_seeds(seeds, linked_asset_ids_by_seed=links)
    matching = next(e for e in result.events if e["event_id"] == target.seed_id)
    assert matching["linked_asset_ids"] == ["AYL_AST_FRS_999"]
