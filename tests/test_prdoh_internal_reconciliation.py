import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "validate_prdoh_internal_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("validate_prdoh_internal_reconciliation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

load_json = MODULE.load_json
validate_receipt = MODULE.validate_receipt
validate_bound_sources = MODULE.validate_bound_sources
bind_prdoh_pws_token = MODULE.bind_prdoh_pws_token

RECEIPT = REPO / "data" / "certification" / "prdoh_internal_reconciliation_v1.json"
R10748 = REPO / "data" / "certification" / "prdoh_10748_structural_v1.json"
S10747 = REPO / "data" / "certification" / "prdoh_10747_semantic_adjudication_v1.json"


def test_frozen_internal_reconciliation_passes():
    doc = load_json(RECEIPT)
    validate_receipt(doc)
    validate_bound_sources(doc, load_json(R10748), load_json(S10747))


def test_equal_prasa_authority_token_binds():
    assert bind_prdoh_pws_token(
        "4945", "4945",
        left_namespace="PRASA_PWS_4DIGIT",
        right_namespace="PRASA_PWS_4DIGIT",
    )


def test_same_name_or_suffix_cannot_bind_cross_namespace():
    assert not bind_prdoh_pws_token(
        "4945", "04945",
        left_namespace="PRASA_PWS_4DIGIT",
        right_namespace="NONPRASA_PWS_7DIGIT",
    )


def test_different_prasa_tokens_never_bind():
    assert not bind_prdoh_pws_token(
        "4945", "4915",
        left_namespace="PRASA_PWS_4DIGIT",
        right_namespace="PRASA_PWS_4DIGIT",
    )


def test_row_fragment_loss_fails_closed():
    doc = load_json(RECEIPT)
    doc["table_fragment_arithmetic"]["combined"]["source_table_fragments"] -= 1
    with pytest.raises(ValueError):
        validate_receipt(doc)


def test_unlisted_report_annex_mismatch_fails_closed():
    doc = load_json(RECEIPT)
    item = doc["exact_reconciliation_checks"][0]
    item["annex"]["violations"] += 1
    with pytest.raises(ValueError):
        validate_receipt(doc)


def test_rtcr_type_arithmetic_cannot_drift():
    doc = load_json(RECEIPT)
    item = next(x for x in doc["exact_reconciliation_checks"] if x["id"] == "NONPRASA-RTCR-MR-COMMUNITY")
    item["report"]["violations"] = 1230
    item["annex"]["violations"] = 1230
    with pytest.raises(ValueError):
        validate_receipt(doc)


def test_source_contradiction_cannot_be_silently_repaired():
    doc = load_json(RECEIPT)
    doc["terminal_source_contradictions"][0]["terminal_handling"] = "REPAIRED"
    with pytest.raises(ValueError):
        validate_receipt(doc)


def test_scope_difference_cannot_be_forced_equal():
    doc = load_json(RECEIPT)
    doc["source_scope_adjudications"][0]["terminal_handling"] = "FORCED_EQUIVALENCE"
    with pytest.raises(ValueError):
        validate_receipt(doc)


def test_nonzero_unresolved_residue_fails_closed():
    doc = load_json(RECEIPT)
    doc["unresolved_count"] = 1
    with pytest.raises(ValueError):
        validate_receipt(doc)
