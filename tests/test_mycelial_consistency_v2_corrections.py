"""Correction-only regression expectations. Synthetic input; no data admission."""
from __future__ import annotations

import copy
import importlib.util
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mycelial_consistency_v2_correction_tests", ROOT / "research/mycelial/consistency_v2.py"
)
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
FIXTURE = ROOT / "tests/fixtures/mycelial_consistency/v2/examples.json"
FLAGS = ("record_admitted", "field_authorized", "public_export_authorized", "model_eligible")


def bundle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]


def rehash(rows):
    # Synthetic fixture builder only; never synthesizes source evidence.
    entities = {(r["record_type"], r[M.KINDS[r["record_type"]][1]]): r for r in rows}
    for row in rows:
        if row["record_type"] != "mycelial_preschedule_commitment":
            continue
        for plan in row["manifest"]["plans"]:
            plan["site_definition_sha256"] = M.logical_sha256(
                entities[("mycelial_field_site", plan["site_id"])])
            plan["target_definition_sha256"] = M.logical_sha256(
                entities[("mycelial_study_target", plan["target_id"])])
            plan["substrate_definition_sha256"] = {
                sid: M.logical_sha256(entities[("mycelial_substrate_unit", sid)])
                for sid in plan["substrate_unit_ids"]
            }
        row["manifest_sha256"] = M.logical_sha256(row["manifest"])


def historical_commitment_bundle():
    rows = bundle()
    predecessor = rows[3]
    predecessor["review_state"] = "superseded"
    successor = copy.deepcopy(predecessor)
    successor.update(
        commitment_id="MYC_PSC_SYNTH_NEW", committed_at="2025-12-31T13:00:00Z",
        supersedes_commitment_id=predecessor["commitment_id"], review_state="needs_review",
    )
    rows.append(successor)
    rows[4]["preschedule_commitment_id"] = successor["commitment_id"]
    rehash(rows)
    return rows


def review_cases():
    cases = []
    row = bundle()[4]
    row["observer_count"] = 10**400
    cases.append(("huge_observer_integer", "CONTROLLED_FAIL", row))
    for name, stamp in (
        ("timezone_underflow", "0001-01-01T00:00:00Z"),
        ("timezone_overflow", "9999-12-31T23:59:59-23:59"),
        ("invalid_rfc3339_offset", "2026-01-01T08:00:00+00:60"),
    ):
        row = bundle()[4]
        row["scheduled_for"] = stamp
        cases.append((name, "FAIL", row))
    row = bundle()[6]
    row.update(status="partial", failure_class="truncation")
    row["original_payload"] = dict(captured=True, byte_count=None, sha256=None, storage_reference=None)
    row["native_metadata"] = dict(kind="none", captured=False, sha256=None, binding_state="missing")
    cases.append(("partial_captured_without_bytes", "FAIL", row))
    cases.append(("legitimate_superseded_predecessor", "PASS_WITH_EXTERNAL_HOLDS", historical_commitment_bundle()))
    return cases


P = SimpleNamespace(rows=bundle, make_cases=review_cases)

def case(name):
    return next(p for n, _, p in P.make_cases() if n == name)

def call(value):
    return M.check_bytes(json.dumps(value, allow_nan=False).encode())

@pytest.mark.parametrize("name", ["huge_observer_integer", "timezone_underflow", "timezone_overflow"])
def test_untrusted_values_produce_controlled_rejection(name):
    # A caller must receive a reason-coded FAIL rather than an unhandled exception.
    result = call(case(name))
    assert result["state"] == "FAIL"
    assert result["reason_codes"]
    assert all(result[f] is False for f in FLAGS)

def test_rfc3339_numeric_offset_does_not_accept_sixty_minutes():
    result = call(case("invalid_rfc3339_offset"))
    assert result["state"] == "FAIL", "Numeric offset minutes must be 00..59"

def test_historical_superseded_reference_does_not_poison_current_amendment():
    rows = case("legitimate_superseded_predecessor")
    result = call(rows)
    for i in (7, 4, 5):
        assert result["rows"][i]["state"] == "PASS_CHECKED_CONSTRAINTS", result["rows"][i]
        assert result["rows"][i]["review_hold_codes"]
        assert all(result["rows"][i][f] is False for f in FLAGS)

def test_original_positive_fixture_still_passes_selected_constraints():
    assert call(P.rows())["state"] == "PASS_CHECKED_CONSTRAINTS"

def test_missing_prerequisite_still_rejects_dependent_observation():
    rows = P.rows()
    del rows[0]
    result = call(rows)
    assert result["state"] == "FAIL"
    obs = next(i for i,r in enumerate(rows) if r["record_type"] == "mycelial_fruiting_observation")
    assert result["rows"][obs]["state"] == "FAIL"

def test_active_use_of_superseded_commitment_stays_rejected():
    rows = P.rows()
    rows[3]["review_state"] = "superseded"
    result = call(rows)
    assert result["rows"][4]["state"] == "FAIL"

def test_original_input_is_not_mutated_or_granted_authority():
    rows = P.rows()
    old = copy.deepcopy(rows)
    result = call(rows)
    assert rows == old
    assert all(result[f] is False for f in FLAGS)
    assert all(all(row[f] is False for f in FLAGS) for row in result["rows"])
    assert result["input_rows"] == result["failed_rows"] + result["passed_checked_constraints"]

def test_partial_receipt_with_missing_captured_identity_is_rejected():
    assert call(case("partial_captured_without_bytes"))["state"] == "FAIL"


# Additional bounds and relationship controls for the four approved findings.
@pytest.mark.parametrize("field,value", [
    ("observer_count", 10**400), ("observer_count", 1e300),
    ("person_minutes", 10**400), ("person_minutes", 1e300),
])
def test_numeric_extremes_fail_without_mutation_or_exception(field, value):
    row = bundle()[4]
    row[field] = value
    before = copy.deepcopy(row)
    result = call(row)
    assert result["state"] == "FAIL"
    assert result["reason_codes"]
    assert row == before
    assert all(result[f] is False for f in FLAGS)


@pytest.mark.parametrize("stamp", [
    "2026-01-01T08:00:00+00:60", "2026-01-01T08:00:00-00:60",
    "2026-01-01T08:00:00+23:60", "2026-01-01T08:00:00+24:00",
    "2026-01-01T08:00:00-24:00", "2026-01-01T08:00:00+99:00",
    "2026-01-01T08:00:00+00:99", "2026-01-01T08:60:00Z",
    "2026-01-01T24:00:00Z", "2026-01-01T08:00:60Z",
])
def test_invalid_offset_components_and_unsupported_clock_values(stamp):
    row = bundle()[4]
    row["scheduled_for"] = stamp
    result = call(row)
    assert result["state"] == "FAIL"
    assert row["scheduled_for"] == stamp
    assert all(result[f] is False for f in FLAGS)


@pytest.mark.parametrize("stamp", [
    "2026-01-01T08:00:00Z", "2026-01-01t08:00:00z",
    "2026-01-01T08:00:00+00:00", "2026-01-01T08:00:00-00:00",
    "2026-01-01T08:00:00+23:59", "2026-01-01T08:00:00-23:59",
    "2026-01-01T08:00:00.123456-04:00",
])
def test_representable_offset_forms_remain_valid_with_holds(stamp):
    row = bundle()[4]
    row["scheduled_for"] = stamp
    result = call(row)
    assert result["state"] == "PASS_CHECKED_CONSTRAINTS", result
    assert result["review_hold_codes"]
    assert row["scheduled_for"] == stamp
    assert all(result[f] is False for f in FLAGS)


@pytest.mark.parametrize("stamp,zone", [
    ("0001-01-01T00:00:00Z", "UTC"),
    ("9999-12-31T23:59:59Z", "UTC"),
    ("0001-01-02T00:00:00Z", "America/Puerto_Rico"),
    ("9999-12-30T23:59:59Z", "America/Puerto_Rico"),
])
def test_representable_calendar_boundaries_do_not_fail_arbitrarily(stamp, zone):
    row = bundle()[4]
    row.update(scheduled_for=stamp, timezone=zone)
    result = call(row)
    assert result["state"] == "PASS_CHECKED_CONSTRAINTS", result
    assert all(result[f] is False for f in FLAGS)


@pytest.mark.parametrize("stamp", [
    "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59",
])
@pytest.mark.parametrize("family,field", [
    ("receipt", "retrieval_started_at"), ("substrate", "registered_at"),
    ("preschedule", "committed_at"), ("observation", "observed_at"),
])
def test_out_of_range_utc_instant_is_rejected_in_every_timestamp_family(stamp, family, field):
    row = next(r for r in bundle() if M.KINDS[r["record_type"]][0] == family)
    row[field] = stamp
    assert call(row)["state"] == "FAIL"


def test_timezone_failure_in_bundle_propagates_but_preserves_other_rows():
    rows = bundle()
    rows[4]["scheduled_for"] = "0001-01-01T00:00:00Z"
    result = call(rows)
    assert result["rows"][4]["state"] == "FAIL"
    assert result["rows"][5]["state"] == "FAIL"
    assert result["rows"][0]["state"] == "PASS_CHECKED_CONSTRAINTS"
    assert result["input_rows"] == result["passed_checked_constraints"] + result["failed_rows"]
    assert all(all(row[f] is False for f in FLAGS) for row in result["rows"])


def test_historical_predecessor_adds_hold_without_reactivating_it():
    rows = historical_commitment_bundle()
    result = call(rows)
    assert result["state"] == "PASS_CHECKED_CONSTRAINTS", result
    assert "HISTORICAL_PREDECESSOR_NOT_ACTIVE" in result["rows"][7]["review_hold_codes"]
    assert "REVIEW_STATE_NOT_ELIGIBLE" in result["rows"][3]["review_hold_codes"]
    assert rows[3]["review_state"] == "superseded"
    assert all(all(row[f] is False for f in FLAGS) for row in result["rows"])


@pytest.mark.parametrize("mode", ["duplicate", "malformed", "cycle", "reversed_time", "rejected"])
def test_historical_edge_does_not_bypass_dependency_guards(mode):
    rows = historical_commitment_bundle()
    if mode == "duplicate":
        rows.append(copy.deepcopy(rows[3]))
    elif mode == "malformed":
        del rows[3]["manifest_sha256"]
    elif mode == "cycle":
        rows[3]["supersedes_commitment_id"] = rows[7]["commitment_id"]
    elif mode == "reversed_time":
        rows[7]["committed_at"] = rows[3]["committed_at"]
    elif mode == "rejected":
        rows[3]["review_state"] = "rejected"
    result = call(rows)
    assert result["state"] == "FAIL"
    assert result["rows"][7]["state"] == "FAIL"
    assert result["rows"][4]["state"] == "FAIL"
    assert result["rows"][5]["state"] == "FAIL"


def historical_substrate_bundle():
    rows = bundle()
    old = rows[2]
    old["review_state"] = "superseded"
    successor = copy.deepcopy(old)
    successor.update(
        substrate_unit_id="MYC_SUB_SYNTH_NEW", registered_at="2025-12-30T14:00:00Z",
        supersedes_substrate_unit_id=old["substrate_unit_id"], review_state="needs_review",
    )
    rows.append(successor)
    rows[3]["manifest"]["plans"][0]["substrate_unit_ids"] = [successor["substrate_unit_id"]]
    rows[4]["substrate_unit_ids"] = [successor["substrate_unit_id"]]
    rows[5]["substrate_unit_id"] = successor["substrate_unit_id"]
    rehash(rows)
    return rows


def test_superseded_substrate_predecessor_is_historical_only():
    rows = historical_substrate_bundle()
    result = call(rows)
    assert result["state"] == "PASS_CHECKED_CONSTRAINTS", result
    assert "HISTORICAL_PREDECESSOR_NOT_ACTIVE" in result["rows"][7]["review_hold_codes"]
    rows[5]["substrate_unit_id"] = rows[2]["substrate_unit_id"]
    result = call(rows)
    assert result["rows"][5]["state"] == "FAIL"
    assert "REFERENCE_REVIEW_STATE_NOT_USABLE" in result["rows"][5]["reason_codes"]


@pytest.mark.parametrize("make_rows", [historical_commitment_bundle, historical_substrate_bundle])
def test_historical_edges_keep_order_independence(make_rows):
    rows = make_rows()
    expected = call(rows)["rows"]
    for seed in range(5):
        indices = list(range(len(rows)))
        random.Random(seed).shuffle(indices)
        result = call([rows[i] for i in indices])
        assert result["rows"] == [expected[i] for i in indices]
        assert result["input_rows"] == result["passed_checked_constraints"] + result["failed_rows"]


def test_correction_keeps_schema_version_and_pin_unchanged():
    assert M.IMPLEMENTATION_VERSION == "2.0.2"
    assert M.SCHEMA_VERSION == "2.0.0"
    assert M.SCHEMA_SHA256 == "bfe7e8628d93adb149c8b79672cbfb4c8025c56d1de3505cb07a9eec2f2a8aba"
