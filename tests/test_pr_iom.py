"""Shape and integrity checks for the PR-IOM baseline package (research/pr_iom_v0_1).

PR-IOM asks which obsolete components in Puerto Rico's electricity and water systems can
be replaced, rebuilt or retrofitted. At v0.1 the package is an evidence baseline, so what
matters is that it cannot overstate: every source ends in a declared terminal state, every
stable file that was reached carries its SHA-256, nothing claims completeness, no request
is recorded as sent, and no component is classified as obsolete without a verified
manufacturer and a receipt.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "research" / "pr_iom_v0_1"
SHA = re.compile(r"^[0-9a-f]{64}$")


def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


RECEIPTS = _load("public_source_receipts.json")
MATRIX = _load("source_coverage_matrix.json")
TAXONOMY = _load("taxonomy.json")
PLAN = _load("execution_plan.json")
BASELINE = _load("asset_universe_baseline.json")
REGISTRY = _load("component_registry.json")
SCHEMA = json.loads(
    (ROOT / "schemas" / "pr-iom" / "v0.1" / "component_record.schema.json").read_text(
        encoding="utf-8"
    )
)
VALIDATOR = Draft202012Validator(SCHEMA)
SOURCES = {s["source_id"]: s for s in RECEIPTS["sources"]}


def test_nothing_is_claimed_complete_and_no_request_was_sent():
    assert RECEIPTS["completeness_claimed"] is False
    assert RECEIPTS["records_requests_sent"] is False
    assert RECEIPTS["raw_documents_committed"] is False
    assert REGISTRY["completeness_claimed"] is False
    assert BASELINE["authoritative"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", RECEIPTS["origin_main_sha"])


def test_every_source_has_a_unique_id_and_a_declared_terminal_state():
    ids = [s["source_id"] for s in RECEIPTS["sources"]]
    assert len(ids) == len(set(ids)) == len(SOURCES)
    assert {s["terminal_state"] for s in RECEIPTS["sources"]} <= set(RECEIPTS["terminal_states"])
    assert set(RECEIPTS["terminal_state_meaning"]) == set(RECEIPTS["terminal_states"])
    assert {s["evidence_tier"] for s in RECEIPTS["sources"]} <= {"T1", "T2", "T3", "T4"}


def test_hashes_are_well_formed_and_unreached_sources_claim_nothing():
    for source in RECEIPTS["sources"]:
        sid = source["source_id"]
        if source["sha256"] is not None:
            assert SHA.match(source["sha256"]), sid
            assert source["reached"] is True and source["bytes"] > 0, sid
        if source["terminal_state"] in {"BLOCKED", "NOT_ATTEMPTED"}:
            assert source["reached"] is False and source["supports"] == [], sid
        if not source["reached"]:
            assert source["sha256"] is None and source["supports"] == [], sid
        if source["reached"] and source["sha256"] is None:
            # Pages the site regenerates: the note must say why there is no hash.
            assert "hash" in source["quality_note"].lower(), sid
        if source["terminal_state"] == "EXHAUSTED":
            assert source["supports"], sid


def test_vendor_material_is_never_evidence_about_a_component():
    for source in RECEIPTS["sources"]:
        if source["source_id"].startswith("VENDOR-"):
            assert source["evidence_tier"] == "T4" and source["supports"] == []
    assert not {r["source_id"] for r in REGISTRY["records"]} & {
        s for s in SOURCES if s.startswith("VENDOR-")
    }


def test_matrix_sources_exist_and_unpublished_metrics_are_requested():
    assert len(MATRIX["metrics"]) == 7
    for row in MATRIX["metrics"]:
        assert row["primary_classification"] in MATRIX["classifications"], row["metric"]
        assert row["coverage_status"] in MATRIX["coverage_statuses"], row["metric"]
        assert set(row["best_public_source"]) <= set(SOURCES), row["metric"]
        if row["coverage_status"] == "covered":
            assert row["included_in_request"] is False, row["metric"]
        if row["coverage_status"] == "not_published":
            assert row["included_in_request"] is True and row["blockers"], row["metric"]
    # The baseline has not answered any of the seven questions.
    assert not [r for r in MATRIX["metrics"] if r["coverage_status"] == "covered"]


def test_plan_has_thirty_steps_in_six_phases_with_resolvable_dependencies():
    steps = PLAN["steps"]
    ids = [s["id"] for s in steps]
    assert ids == [f"PR-IOM-001-S{n:02d}" for n in range(1, 31)]
    assert [p["phase"] for p in PLAN["phases"]] == list(range(6))
    assert {s["phase"] for s in steps} == set(range(6))
    position = {sid: i for i, sid in enumerate(ids)}
    for step in steps:
        assert step["state"] in PLAN["states"], step["id"]
        assert step["exit_criteria"], step["id"]
        for dep in step["dependency"]:
            assert dep in position and dep != step["id"], step["id"]
        if step["state"] == "done_v0_1":
            assert step["evidence"] and step["blocker"] is None, step["id"]
        if step["state"] == "partial":
            assert step["evidence"] and step["blocker"], step["id"]
        for ref in step["evidence"]:
            assert ref in SOURCES or (ROOT / ref).is_file(), (step["id"], ref)
    # Nothing past identification can be marked done before identification is.
    done = {s["id"] for s in steps if s["state"] == "done_v0_1"}
    for step in steps:
        if step["id"] in done:
            assert set(step["dependency"]) <= done, step["id"]


def test_taxonomy_matches_the_record_schema():
    props = SCHEMA["properties"]
    assert [c["class_id"] for c in TAXONOMY["infrastructure_classes"]] == props[
        "infrastructure_class"
    ]["enum"]
    assert [s["code"] for s in TAXONOMY["obsolescence_statuses"]] == props[
        "obsolescence_status"
    ]["enum"]
    assert [s["code"] for s in TAXONOMY["replacement_strategies"]] == props[
        "candidate_strategies"
    ]["items"]["enum"]
    assert [c["code"] for c in TAXONOMY["operator_condition_claims"]] == props[
        "operator_condition_claim"
    ]["enum"]
    assert len(TAXONOMY["evaluation_criteria"]) == 6
    assert TAXONOMY["definition_precedent"]["source_id"] in SOURCES


def test_schema_is_valid_and_every_record_conforms():
    Draft202012Validator.check_schema(SCHEMA)
    ids = [r["component_id"] for r in REGISTRY["records"]]
    assert len(ids) == len(set(ids))
    assert REGISTRY["record_schema"] == "schemas/pr-iom/v0.1/component_record.schema.json"
    for record in REGISTRY["records"]:
        VALIDATOR.validate(record)


def test_every_record_is_bound_to_a_hashed_receipt():
    for record in REGISTRY["records"]:
        source = SOURCES[record["source_id"]]
        assert source["reached"] is True, record["component_id"]
        assert record["source_receipt_sha256"] == source["sha256"], record["component_id"]
        assert record["evidence_tier"] == source["evidence_tier"], record["component_id"]


def test_no_record_is_classified_beyond_what_was_verified():
    for record in REGISTRY["records"]:
        if record["manufacturer"] is None:
            assert record["obsolescence_status"] == "O0_UNVERIFIED", record["component_id"]
            assert record["candidate_strategies"] == [], record["component_id"]
            assert record["review_status"] == "needs_review", record["component_id"]
        if not record["asset_ids"]:
            assert record["identity_verification_status"] == "UNVERIFIED", record["component_id"]
        if record["disclosure"] == "operator_restricted":
            assert record["review_status"] != "accepted", record["component_id"]


def test_asset_ids_and_baseline_inputs_match_the_repository_data():
    assets = ROOT / "data" / "utility_assets.jsonl"
    if not assets.is_file():
        pytest.skip("data/utility_assets.jsonl is not present in this checkout")
    known = set()
    with assets.open(encoding="utf-8") as handle:
        for line in handle:
            known.add(json.loads(line)["asset_id"])
    for record in REGISTRY["records"]:
        assert set(record["asset_ids"]) <= known, record["component_id"]
    for asset in BASELINE["power_generation_assets"]:
        assert asset["asset_id"] in known
    for item in BASELINE["inputs"]:
        assert SHA.match(item["sha256"]) and item["rows"] > 0, item["path"]
    assert {d["state"] for d in BASELINE["unresolved_dependencies"]} == {"NOT_IN_REPOSITORY"}


def _valid_record() -> dict:
    return copy.deepcopy(REGISTRY["records"][0])


def test_schema_rejects_a_status_without_a_verified_manufacturer():
    bad = _valid_record()
    bad["obsolescence_status"] = "O1_OEM_DISCONTINUED"
    with pytest.raises(ValidationError):
        VALIDATOR.validate(bad)
    good = {
        **bad,
        "manufacturer": "Example Works",
        "identity_verification_status": "VERIFIED",
        "candidate_strategies": ["R5"],
    }
    VALIDATOR.validate(good)


def test_schema_rejects_strategies_on_an_unverified_record():
    bad = _valid_record()
    bad["candidate_strategies"] = ["R4"]
    with pytest.raises(ValidationError):
        VALIDATOR.validate(bad)


def test_schema_rejects_an_accepted_operator_restricted_record():
    bad = _valid_record()
    bad["disclosure"] = "operator_restricted"
    bad["review_status"] = "accepted"
    with pytest.raises(ValidationError):
        VALIDATOR.validate(bad)


def test_schema_rejects_unknown_fields_and_bad_ids():
    extra = {**_valid_record(), "exact_location": "turbine hall"}
    with pytest.raises(ValidationError):
        VALIDATOR.validate(extra)
    bad_id = {**_valid_record(), "component_id": "IOM-1"}
    with pytest.raises(ValidationError):
        VALIDATOR.validate(bad_id)
