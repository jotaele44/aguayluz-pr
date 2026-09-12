"""Isolated developer tests: no production app import or scientific admission."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import random
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "research/mycelial/consistency_v2.py"
SPEC = importlib.util.spec_from_file_location("mycelial_consistency_v2_isolated", MODULE)
assert SPEC is not None and SPEC.loader is not None
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
FIXTURE = ROOT / "tests/fixtures/mycelial_consistency/v2/examples.json"
FLAGS = ("record_admitted", "field_authorized", "public_export_authorized", "model_eligible")


def bundle():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]


def record(family):
    return next(x for x in bundle() if M.KINDS[x["record_type"]][0] == family)


def mutate(family, path, value):
    row = record(family)
    dest = row
    for key in path[:-1]:
        dest = dest[key]
    if value == "__DELETE__":
        del dest[path[-1]]
    else:
        dest[path[-1]] = value
    return row


def regressions():
    """The 18 prior failure classes, explicitly expressed in v2 fixtures."""
    m = dict(measurement_id="MYC_MSR_SYNTH_DUP", metric="cap_diameter", value=1,
             unit="mm", method="synthetic", scale_evidence=None, uncertainty=None)
    rows = [
        ("permission_reference_missing", mutate("site", ["permission_reference"], "__DELETE__")),
        ("withheld_locator_retained", mutate("site", ["location", "mode"], "withheld")),
        ("location_precision_conflict", mutate("site", ["location", "precision_tier"], "withheld")),
        ("observer_count_mismatch", mutate("survey", ["observer_count"], 2)),
        ("survey_time_reversed", mutate("survey", ["ended_at"], "2026-01-01T08:01:00-04:00")),
        ("effort_with_zero_duration", mutate("survey", ["ended_at"], "2026-01-01T08:02:00-04:00")),
        ("effort_exceeds_capacity", mutate("survey", ["person_minutes"], 31)),
        ("unknown_time_zone", mutate("survey", ["timezone"], "Synthetic/NotARealZone")),
        ("visible_body_exact_zero_count", mutate("observation", ["count", "value"], 0)),
        ("count_range_reversed", mutate("observation", ["count"], dict(method="range", value=None, lower_bound=3, upper_bound=1))),
        ("unknown_count_with_value", mutate("observation", ["count", "method"], "unknown")),
        ("duplicate_measurement_id", mutate("observation", ["measurements"], [m, copy.deepcopy(m)])),
        ("target_kind_rank_conflict", mutate("target", ["kind"], "guild")),
        ("acquisition_time_reversed", mutate("receipt", ["retrieval_completed_at"], "2025-12-31T23:00:00Z")),
        ("uncaptured_metadata_hash_and_binding", mutate("receipt", ["native_metadata", "captured"], False)),
        ("captured_metadata_hash_missing", mutate("receipt", ["native_metadata", "sha256"], None)),
        ("complete_source_http_error", mutate("receipt", ["transport", "status_code"], 503)),
        ("nonfinite_effort", mutate("survey", ["person_minutes"], float("inf"))),
    ]
    return rows


@pytest.mark.parametrize("name,row", regressions(), ids=[x[0] for x in regressions()])
def test_prior_counterexample_class_rejected(name, row):
    before = copy.deepcopy(row)
    result = M.check_record(row)
    assert result["state"] == "FAIL", name
    assert row == before
    assert all(result[f] is False for f in FLAGS)


@pytest.mark.parametrize("family", ["site", "target", "substrate", "preschedule", "survey", "observation", "receipt"])
def test_each_positive_record_has_holds_and_zero_authority(family):
    result = M.check_record(record(family))
    assert result["state"] == "PASS_CHECKED_CONSTRAINTS", result
    assert result["review_hold_codes"]
    assert all(result[f] is False for f in FLAGS)


def test_contracts_valid_and_only_local_references():
    root = json.loads(M.SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(root)
    assert len(root["$defs"]) == 7
    for kind in M.KINDS:
        Draft202012Validator.check_schema(M.schema_for(kind))
    def walk(v):
        if isinstance(v, dict):
            if "$ref" in v:
                assert v["$ref"].startswith("#/")
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(root)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"x":{"a":1,"a":2}}', b'{"n":NaN}', b'{"n":Infinity}', b'{"n":-Infinity}', b'{"n":1e309}', b'\xff', b'{', b'{"x":"\\ud800"}', b'{"n":'+b'9'*6000+b'}'])
def test_strict_input_failures(raw):
    assert M.check_bytes(raw)["state"] == "FAIL"


def test_resource_limits_and_cycles():
    assert M.check_bytes(b" " * (M.MAX_INPUT_BYTES + 1))["state"] == "FAIL"
    v = []
    v.append(v)
    with pytest.raises(M.InputRejected, match="STRUCTURE_RESOURCE_LIMIT"):
        M.check_bundle(v)
    with pytest.raises(M.InputRejected):
        M.check_bundle([])
    with pytest.raises(M.InputRejected):
        M.check_bundle([None] * (M.MAX_ROWS + 1))


@pytest.mark.parametrize("value", [None, [], 3, {"record_type": []}, {"record_type": "unknown"}])
def test_unknown_record_types(value):
    assert M.check_record(value)["state"] == "FAIL"


def test_bytes_type_and_nonjson_object_handling():
    with pytest.raises(M.InputRejected):
        M.load_strict("{}")
    assert M.check_record({1: "x"})["state"] == "FAIL"
    assert M.check_record({"record_type": "mycelial_field_site", "x": set()})["state"] == "FAIL"


def test_no_mutation_no_echo_and_no_authority():
    rows = bundle()
    rows[0]["location"].update(mode="withheld", precision_tier="withheld", generalized_reference="SECRET_LOCATOR_DO_NOT_ECHO")
    before = copy.deepcopy(rows)
    out = M.check_bundle(rows)
    assert rows == before
    text = json.dumps(out)
    assert "SECRET_LOCATOR_DO_NOT_ECHO" not in text
    assert rows[0]["site_id"] not in text
    assert all(out[f] is False for f in FLAGS)
    assert all(all(r[f] is False for f in FLAGS) for r in out["rows"])


def test_complete_bundle_conservation_and_bytes_entrypoint():
    rows = bundle()
    out = M.check_bytes(json.dumps(rows).encode())
    assert out["state"] == "PASS_CHECKED_CONSTRAINTS", out
    assert out["input_rows"] == out["passed_checked_constraints"] + out["failed_rows"] == 7
    assert out["canonical_records_admitted"] == 0


@pytest.mark.parametrize("invalid_duplicate", [False, True])
def test_duplicate_candidate_sets_include_invalid_records(invalid_duplicate):
    rows = bundle()
    dup = copy.deepcopy(rows[0])
    if invalid_duplicate:
        del dup["permission_reference"]
    rows.append(dup)
    out = M.check_bundle(rows)
    assert out["rows"][0]["state"] == out["rows"][-1]["state"] == "FAIL"
    assert any(c["candidate_rows"] == [0, 7] for c in out["reference_candidates"])
    assert out["rows"][4]["state"] == out["rows"][5]["state"] == "FAIL"


@pytest.mark.parametrize("mode", ["valid", "record_failure", "cross_failure", "duplicate"])
def test_order_independent_dispositions(mode):
    rows = bundle()
    if mode == "record_failure":
        del rows[0]["permission_reference"]
    elif mode == "cross_failure":
        rows[2]["registered_at"] = "2025-12-31T13:00:00Z"
    elif mode == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    expected = M.check_bundle(rows)["rows"]
    for seed in range(8):
        indices = list(range(len(rows)))
        random.Random(seed).shuffle(indices)
        got = M.check_bundle([rows[i] for i in indices])
        assert got["rows"] == [expected[i] for i in indices]
        assert got["input_rows"] == got["passed_checked_constraints"] + got["failed_rows"]


@pytest.mark.parametrize("field", ["site", "target", "substrate", "preschedule", "survey"])
def test_missing_dependencies_fail_closed(field):
    rows = [r for r in bundle() if M.KINDS[r["record_type"]][0] != field]
    out = M.check_bundle(rows)
    assert out["state"] == "FAIL"
    obs = next(i for i,r in enumerate(rows) if r["record_type"] == "mycelial_fruiting_observation")
    assert out["rows"][obs]["state"] == "FAIL"


@pytest.mark.parametrize("date", ["not-a-date", "2026-01-01T12:00:00", "2026-02-30T12:00:00Z", "2026-01-01T99:00:00Z"])
def test_timestamp_validation_has_no_optional_dependency_bypass(date):
    row = record("survey")
    row["scheduled_for"] = date
    assert M.check_record(row)["state"] == "FAIL"


def test_mutated_schema_copy_cannot_poison_later_validation():
    value = M.schema_for("mycelial_field_site")
    value.clear()
    assert M.check_record(record("site"))["state"] == "PASS_CHECKED_CONSTRAINTS"


def test_schema_on_disk_tamper_fails_closed(tmp_path, monkeypatch):
    p = tmp_path / "schema.json"
    p.write_text("{}")
    monkeypatch.setattr(M, "SCHEMA_PATH", p)
    assert M.check_record(record("site"))["reason_codes"] == ["TRUSTED_SCHEMA_HASH_MISMATCH"]


def test_v1_never_implicitly_upgraded():
    row = record("site")
    row["schema_version"] = "1.0.0"
    assert M.check_record(row)["state"] == "FAIL"


def test_minimum_estimate_is_explicit_lower_bound_not_zero():
    row = record("observation")
    row["count"] = dict(method="minimum_estimate", value=None, lower_bound=2, upper_bound=None)
    assert M.check_record(row)["state"] == "PASS_CHECKED_CONSTRAINTS"
    row["count"]["lower_bound"] = 0
    assert M.check_record(row)["state"] == "FAIL"


def test_whitespace_permission_reference_fails():
    row = record("site")
    row["permission_reference"] = "   "
    assert M.check_record(row)["state"] == "FAIL"


def test_positive_incomplete_visit_retained_but_not_negative():
    rows = bundle()
    rows[4].update(visit_status="incomplete", outcome_reason="synthetic interrupted visit")
    assert M.check_bundle(rows)["state"] == "PASS_CHECKED_CONSTRAINTS"
    rows[4]["detection_status"] = "not_detected"
    assert M.check_record(rows[4])["state"] == "FAIL"


def test_missed_has_no_body_and_no_invented_negative():
    rows = bundle()
    rows.pop(5)
    rows[4].update(visit_status="missed", detection_status="not_assessed", started_at=None, ended_at=None, person_minutes=0, observer_count=0, observer_pseudonyms=[], qualification_classes=[], substrate_unit_ids=[], outcome_reason="synthetic missed visit")
    assert M.check_bundle(rows)["state"] == "PASS_CHECKED_CONSTRAINTS"
    rows[4]["detection_status"] = "not_detected"
    assert M.check_record(rows[4])["state"] == "FAIL"


def test_zero_effort_aborted_visit_allowed_but_detection_rejected():
    row = record("survey")
    row.update(visit_status="aborted", detection_status="not_assessed", person_minutes=0, ended_at=row["started_at"], substrate_unit_ids=[], outcome_reason="synthetic no search")
    assert M.check_record(row)["state"] == "PASS_CHECKED_CONSTRAINTS"
    row["detection_status"] = "detected"
    assert M.check_record(row)["state"] == "FAIL"


def test_completed_nondetection_requires_no_linked_body():
    rows = bundle()
    rows[4].update(detection_status="not_detected", non_detection_interpretation="documented non-detection under stated effort; not proof of absence")
    assert M.check_bundle(rows[:5] + rows[6:])["state"] == "PASS_CHECKED_CONSTRAINTS"
    assert "BODY_LINKED_TO_NONDETECTING_SURVEY" in M.check_bundle(rows)["rows"][5]["reason_codes"]


def test_observation_time_and_substrate_binding():
    rows = bundle()
    rows[5]["observed_at"] = "2026-01-02T08:05:00-04:00"
    assert "OBSERVATION_OUTSIDE_SURVEY_INTERVAL" in M.check_bundle(rows)["rows"][5]["reason_codes"]
    rows[5]["substrate_unit_id"] = "MYC_SUB_UNKNOWN"
    assert "MISSING_OR_AMBIGUOUS_REFERENCE" in M.check_bundle(rows)["rows"][5]["reason_codes"]


def test_preschedule_hash_tampering_rejected_without_rehash():
    row = record("preschedule")
    row["manifest"]["plans"][0]["intended_person_minutes"] = 40
    assert "PLAN_MANIFEST_HASH_MISMATCH" in M.check_record(row)["reason_codes"]


def test_rehashed_plan_still_requires_definition_binding():
    rows = bundle()
    rows[3]["manifest"]["plans"][0]["target_definition_sha256"] = "0" * 64
    rows[3]["manifest_sha256"] = M.logical_sha256(rows[3]["manifest"])
    assert "PLAN_DEFINITION_HASH_MISMATCH" in M.check_bundle(rows)["rows"][3]["reason_codes"]


def test_timestamp_alone_never_proves_preschedule_authority():
    out = M.check_record(record("preschedule"))
    assert "PRESCHEDULE_AUTHORITY_NOT_VERIFIED" in out["review_hold_codes"]
    assert out["field_authorized"] is False


def test_late_commitment_and_backfilled_actual_visit():
    row = record("preschedule")
    row["committed_at"] = "2026-01-02T12:00:00Z"
    assert "COMMITMENT_NOT_BEFORE_PLANNED_VISIT" in M.check_record(row)["reason_codes"]
    rows = bundle()
    rows[4].update(started_at="2025-12-30T12:00:00Z", ended_at="2025-12-30T12:30:00Z")
    assert "COMMITMENT_NOT_BEFORE_ACTUAL_VISIT" in M.check_bundle(rows)["rows"][4]["reason_codes"]


def test_duplicate_entries_and_hash_mapping_mismatch():
    row = record("preschedule")
    row["manifest"]["plans"].append(copy.deepcopy(row["manifest"]["plans"][0]))
    row["manifest_sha256"] = M.logical_sha256(row["manifest"])
    assert "DUPLICATE_PLAN_IDENTITY" in M.check_record(row)["reason_codes"]
    row = record("preschedule")
    row["manifest"]["plans"][0]["substrate_definition_sha256"]["MYC_SUB_EXTRA"] = "0" * 64
    row["manifest_sha256"] = M.logical_sha256(row["manifest"])
    assert "PLAN_SUBSTRATE_HASH_SET_MISMATCH" in M.check_record(row)["reason_codes"]


def test_cycle_is_blocked_and_candidate_references_retained():
    rows = bundle()
    a = rows[3]
    b = copy.deepcopy(a)
    b["commitment_id"] = "MYC_PSC_SYNTH_B"
    a["supersedes_commitment_id"] = b["commitment_id"]
    b["supersedes_commitment_id"] = a["commitment_id"]
    rows.append(b)
    out = M.check_bundle(rows)
    assert "CYCLIC_OR_CYCLE_DEPENDENT_REFERENCE" in out["rows"][3]["reason_codes"]
    assert out["rows"][4]["state"] == out["rows"][5]["state"] == "FAIL"


def test_unexamined_scope_cannot_be_completed_negative():
    rows = bundle()
    rows[4]["substrate_unit_ids"] = []
    assert "COMPLETED_SUBSTRATE_SCOPE_MISMATCH" in M.check_bundle(rows)["rows"][4]["reason_codes"]


@pytest.mark.parametrize("code", [None, 204, 206, 302, 403, 503])
def test_complete_receipt_transport_codes(code):
    row = record("receipt")
    row["transport"]["status_code"] = code
    assert M.check_record(row)["state"] == "FAIL"


def test_acquired_bytes_do_not_establish_native_metadata_or_licensing():
    row = record("receipt")
    row["rights_state"] = "unresolved_hold"
    out = M.check_record(row)
    assert out["state"] == "PASS_CHECKED_CONSTRAINTS"
    assert "RIGHTS_COORDINATE_POLICY_NOT_VERIFIED" in out["review_hold_codes"]
    assert out["record_admitted"] is False


def test_import_only_no_application_or_network_or_persistence_hooks():
    tree = ast.parse(MODULE.read_text())
    banned = {"requests", "httpx", "socket", "sqlite3", "fastapi", "subprocess", "server"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] in banned for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned
    assert not hasattr(M, "app") and not hasattr(M, "router")
    assert not hasattr(M, "main")


def test_fixture_is_synthetic_not_real_data():
    assert json.loads(FIXTURE.read_text())["classification"] == "SYNTHETIC_ONLY_NOT_BIOLOGICAL_OR_ACQUISITION_EVIDENCE"
