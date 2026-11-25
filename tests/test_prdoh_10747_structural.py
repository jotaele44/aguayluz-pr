import copy
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "validate_prdoh_10747_structural.py"
SPEC = importlib.util.spec_from_file_location("validate_prdoh_10747_structural", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

load_ledger = MODULE.load_ledger
validate_ledger = MODULE.validate_ledger
validate_semantic_adjudication = MODULE.validate_semantic_adjudication
load_semantic_adjudication = MODULE.load_semantic_adjudication
LEDGER = REPO / "data" / "certification" / "prdoh_10747_structural_v1.json.gz.b64"
SEMANTICS = REPO / "data" / "certification" / "prdoh_10747_semantic_adjudication_v1.json"


def test_frozen_10747_ledger_passes():
    doc = load_ledger(LEDGER)
    validate_ledger(doc)
    validate_semantic_adjudication(doc, load_semantic_adjudication(SEMANTICS))


def test_level2_identity_scope_is_prasa_not_nonprasa():
    doc = load_ledger(LEDGER)
    adjudication = load_semantic_adjudication(SEMANTICS)
    item = adjudication["adjudications"][0]
    assert item["corrected_semantic_scope"] == "PRASA_IDENTITY_REFERENCE"
    validate_semantic_adjudication(doc, adjudication)


def test_level2_semantic_reclassification_cannot_change_arithmetic():
    doc = load_ledger(LEDGER)
    adjudication = load_semantic_adjudication(SEMANTICS)
    adjudication["arithmetic_effect"]["source_rows_added"] = 1
    with pytest.raises(ValueError):
        validate_semantic_adjudication(doc, adjudication)


def test_level2_pws_tokens_cannot_drift():
    doc = load_ledger(LEDGER)
    adjudication = load_semantic_adjudication(SEMANTICS)
    adjudication["adjudications"][0]["raw_pws_tokens"] = ["2672", "9999"]
    with pytest.raises(ValueError):
        validate_semantic_adjudication(doc, adjudication)


def test_source_sha_drift_fails_closed():
    doc = load_ledger(LEDGER)
    doc["source_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate_ledger(doc)


def test_reference_row_cannot_enter_violation_denominator():
    doc = load_ledger(LEDGER)
    doc["violation_count_cells"][0]["table_id"] = "24"
    with pytest.raises(ValueError):
        validate_ledger(doc)


def test_metric_row_loss_fails_closed():
    doc = load_ledger(LEDGER)
    doc["violation_count_cells"].pop()
    with pytest.raises(ValueError):
        validate_ledger(doc)


def test_historical_summary_detail_contradiction_cannot_be_repaired_silently():
    doc = load_ledger(LEDGER)
    finding = next(x for x in doc["source_internal_findings"] if x["id"] == "10747-CONTR-002")
    finding["terminal_handling"] = "REPAIRED"
    with pytest.raises(ValueError):
        validate_ledger(doc)


def test_nonadditive_analyte_rows_cannot_be_summed_into_new_source_value():
    doc = load_ledger(LEDGER)
    row = next(
        x
        for x in doc["violation_count_cells"]
        if x["table_id"] == "14" and x["metric_type"] == "MR"
    )
    row["violations"] = 29
    with pytest.raises(ValueError):
        validate_ledger(doc)


def test_exemption_continuation_cannot_be_duplicated():
    doc = load_ledger(LEDGER)
    table = next(x for x in doc["reference_tables"] if x["table_id"] == "24")
    table["rows"].append(copy.deepcopy(table["rows"][0]))
    with pytest.raises(ValueError):
        validate_ledger(doc)
