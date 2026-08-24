"""Entity promotion: only approved links become crosswalk rows, with the
observation's provider joined in, and schema-valid output."""

from __future__ import annotations

from aguayluz.models import validate_against_schema
from aguayluz.regulatory_promotion import promote_approved_links

OBSERVATION = {
    "observation_id": "AYL_REGOBS_USGS_abc123",
    "record_family": "entity",
    "provider": "USGS",
    "provider_record_id": "50038100",
    "observed_at": "2026-08-19T21:00:00Z",
    "retrieved_at": "2026-08-19T21:00:00Z",
    "source_receipt_id": "AYL_REGRCPT_USGS_def456",
    "normalization_version": "usgs/v1",
    "evidence_tier": "T1",
    "freshness_state": "current",
    "identifiers": [{"scheme": "usgs_site_no", "value": "50038100"}],
    "payload": {"name": "RIO GRANDE DE ARECIBO"},
}

APPROVED_LINK = {
    "candidate_id": "AYL_REGLINK_abcdef123456",
    "observation_id": OBSERVATION["observation_id"],
    "candidate_asset_id": "USGS_50038100",
    "decision_state": "approved",
    "match_strength": "hard_identifier",
    "match_features": [{
        "feature": "provider_identifier", "value": "usgs_site_no:50038100",
        "source_observation_id": OBSERVATION["observation_id"],
    }],
    "contradictions": [],
    "created_at": "2026-08-19T21:00:00Z",
    "decided_at": "2026-08-19T22:00:00Z",
    "decided_by": "operator-1",
    "decision_rationale": "Exact site number match verified.",
}

NEEDS_REVIEW_LINK = {**APPROVED_LINK, "candidate_id": "AYL_REGLINK_needsreview01", "decision_state": "needs_review"}
REJECTED_LINK = {**APPROVED_LINK, "candidate_id": "AYL_REGLINK_rejected01", "decision_state": "rejected"}


def test_promote_only_approved_links():
    rows = promote_approved_links(
        [APPROVED_LINK, NEEDS_REVIEW_LINK, REJECTED_LINK], [OBSERVATION]
    )
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == APPROVED_LINK["candidate_id"]


def test_promoted_row_joins_provider_from_observation():
    rows = promote_approved_links([APPROVED_LINK], [OBSERVATION])
    assert rows[0]["provider"] == "USGS"
    assert rows[0]["asset_id"] == "USGS_50038100"
    assert rows[0]["observation_id"] == OBSERVATION["observation_id"]


def test_promoted_row_carries_full_decision_provenance():
    rows = promote_approved_links([APPROVED_LINK], [OBSERVATION])
    row = rows[0]
    assert row["decided_at"] == APPROVED_LINK["decided_at"]
    assert row["decided_by"] == APPROVED_LINK["decided_by"]
    assert row["decision_rationale"] == APPROVED_LINK["decision_rationale"]


def test_crosswalk_id_derives_from_candidate_id():
    rows = promote_approved_links([APPROVED_LINK], [OBSERVATION])
    assert rows[0]["crosswalk_id"] == "AYL_REGXWALK_abcdef123456"


def test_promote_skips_link_with_no_matching_observation():
    orphan_link = {**APPROVED_LINK, "observation_id": "AYL_REGOBS_USGS_does_not_exist"}
    assert promote_approved_links([orphan_link], [OBSERVATION]) == []


def test_promote_no_approved_links_returns_empty():
    assert promote_approved_links([NEEDS_REVIEW_LINK, REJECTED_LINK], [OBSERVATION]) == []


def test_promoted_rows_validate_against_schema():
    rows = promote_approved_links([APPROVED_LINK], [OBSERVATION])
    assert rows
    for row in rows:
        validate_against_schema("regulatory_entity_crosswalk", row)


def test_promote_never_touches_decision_state_of_input_links():
    # Guard against a future refactor accidentally mutating the input in place.
    links = [dict(APPROVED_LINK)]
    promote_approved_links(links, [OBSERVATION])
    assert links[0]["decision_state"] == "approved"
