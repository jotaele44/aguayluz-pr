"""Entity-link candidate generation: hard-identifier matching, municipality
contradiction detection, deterministic ids, and schema validity of the output."""

from __future__ import annotations

from aguayluz.models import validate_against_schema
from aguayluz.regulatory_links import (
    build_asset_link_index,
    generate_all_candidates,
    generate_candidates,
)

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
    "payload": {
        "name": "RIO GRANDE DE ARECIBO AT ARECIBO, PR",
        "site_type_code": "ST",
        "county_name": "Arecibo Municipio",
    },
}

MATCHING_ASSET = {
    "asset_id": "USGS_50038100",
    "asset_name": "Rio Grande de Arecibo",
    "asset_type": "water",
    "municipality": "Arecibo",
}

MISMATCHED_MUNICIPALITY_ASSET = {
    "asset_id": "USGS_50038100",
    "asset_name": "Rio Grande de Arecibo",
    "asset_type": "water",
    "municipality": "Ponce",
}

SECOND_PREFIX_ASSET = {
    "asset_id": "USGSFM_50038100",
    "asset_name": "Rio Grande de Arecibo (field measurement)",
    "asset_type": "water",
    "municipality": "Arecibo",
}


def test_build_asset_link_index_maps_site_no_to_multiple_prefixed_assets():
    site_index, muni_index = build_asset_link_index([MATCHING_ASSET, SECOND_PREFIX_ASSET])
    assert set(site_index["50038100"]) == {"USGS_50038100", "USGSFM_50038100"}
    assert muni_index["USGS_50038100"] == "Arecibo"


def test_build_asset_link_index_ignores_non_usgs_assets():
    site_index, _ = build_asset_link_index([{"asset_id": "PWR_12345", "municipality": "Ponce"}])
    assert site_index == {}


def test_generate_candidates_hard_identifier_match_no_contradiction():
    site_index, muni_index = build_asset_link_index([MATCHING_ASSET])
    candidates = generate_candidates(OBSERVATION, site_index, muni_index)

    assert len(candidates) == 1
    c = candidates[0]
    assert c["observation_id"] == OBSERVATION["observation_id"]
    assert c["candidate_asset_id"] == "USGS_50038100"
    assert c["decision_state"] == "proposed"
    assert c["match_strength"] == "hard_identifier"
    assert c["contradictions"] == []
    assert c["match_features"][0]["feature"] == "provider_identifier"
    assert c["match_features"][0]["value"] == "usgs_site_no:50038100"


def test_generate_candidates_one_per_matching_asset_row():
    site_index, muni_index = build_asset_link_index([MATCHING_ASSET, SECOND_PREFIX_ASSET])
    candidates = generate_candidates(OBSERVATION, site_index, muni_index)
    assert {c["candidate_asset_id"] for c in candidates} == {"USGS_50038100", "USGSFM_50038100"}
    assert len({c["candidate_id"] for c in candidates}) == 2  # distinct ids per asset


def test_generate_candidates_flags_municipality_mismatch_as_needs_review():
    site_index, muni_index = build_asset_link_index([MISMATCHED_MUNICIPALITY_ASSET])
    candidates = generate_candidates(OBSERVATION, site_index, muni_index)

    assert len(candidates) == 1
    c = candidates[0]
    assert c["decision_state"] == "needs_review"
    assert len(c["contradictions"]) == 1
    assert c["contradictions"][0]["kind"] == "municipality"
    assert "Ponce" in c["contradictions"][0]["detail"]


def test_generate_candidates_treats_unknown_municipality_as_missing_not_contradicting():
    # "unknown" is a real placeholder value in data/utility_assets.jsonl (e.g.
    # USGSWQ_ rows from scripts/ingest_usgs_water_quality.py) -- it must not be
    # treated as a disagreeing claim.
    asset = {**MATCHING_ASSET, "municipality": "unknown"}
    site_index, muni_index = build_asset_link_index([asset])
    candidates = generate_candidates(OBSERVATION, site_index, muni_index)

    assert len(candidates) == 1
    assert candidates[0]["decision_state"] == "proposed"
    assert candidates[0]["contradictions"] == []


def test_generate_candidates_no_match_returns_empty():
    site_index, muni_index = build_asset_link_index([])
    assert generate_candidates(OBSERVATION, site_index, muni_index) == []


def test_generate_candidates_observation_without_usgs_identifier_returns_empty():
    other = {**OBSERVATION, "identifiers": [{"scheme": "epa_id", "value": "PRR000001"}]}
    site_index, muni_index = build_asset_link_index([MATCHING_ASSET])
    assert generate_candidates(other, site_index, muni_index) == []


def test_candidate_id_is_deterministic_and_independent_of_decision_state():
    site_index, muni_index = build_asset_link_index([MATCHING_ASSET])
    first = generate_candidates(OBSERVATION, site_index, muni_index)[0]
    second = generate_candidates(OBSERVATION, site_index, muni_index)[0]
    assert first["candidate_id"] == second["candidate_id"]


def test_candidate_id_differs_for_different_asset_or_observation():
    site_index, muni_index = build_asset_link_index([MATCHING_ASSET, SECOND_PREFIX_ASSET])
    candidates = generate_candidates(OBSERVATION, site_index, muni_index)
    ids = {c["candidate_id"] for c in candidates}
    assert len(ids) == 2

    other_obs = {**OBSERVATION, "observation_id": "AYL_REGOBS_USGS_different"}
    site_index2, muni_index2 = build_asset_link_index([MATCHING_ASSET])
    other_candidate = generate_candidates(other_obs, site_index2, muni_index2)[0]
    assert other_candidate["candidate_id"] not in ids


def test_generate_all_candidates_never_emits_approved():
    candidates = generate_all_candidates(
        [OBSERVATION], [MATCHING_ASSET, MISMATCHED_MUNICIPALITY_ASSET]
    )
    assert all(c["decision_state"] != "approved" for c in candidates)


def test_generated_candidates_validate_against_schema():
    candidates = generate_all_candidates([OBSERVATION], [MATCHING_ASSET])
    assert candidates
    for candidate in candidates:
        validate_against_schema("regulatory_entity_link", candidate)
