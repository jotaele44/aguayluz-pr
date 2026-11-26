#!/usr/bin/env python3
"""Fail-closed validator for the frozen PRDOH 10747 structural ledger."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

SOURCE_SHA = "748529762de1b6661b5484957a7662bd233a37aaf371482cdc14bbf5ac584772"
JSON_SHA = "6f4d7ffd53399ed21be12009e50bcc190bff5f3f71e37db43e54962c2ffd9b26"
GZIP_SHA = "f744c59090f58bc4b387c048ba728becd1aeaffee46c3b9502d40cf9784468db"
EXPECTED_TABLES = 29
EXPECTED_DATA_ROWS = 221
EXPECTED_TOTAL_ROWS = 2
EXPECTED_CONTINUATIONS = 1
EXPECTED_METRICS = 346


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_ledger(path: Path) -> dict[str, Any]:
    encoded = path.read_text(encoding="utf-8").strip()
    compressed = base64.b64decode(encoded, validate=True)
    if _sha256(compressed) != GZIP_SHA:
        raise ValueError("10747 gzip manifestation hash mismatch")
    payload = gzip.decompress(compressed)
    if _sha256(payload) != JSON_SHA:
        raise ValueError("10747 decoded JSON hash mismatch")
    return json.loads(payload)


def load_semantic_adjudication(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_semantic_adjudication(doc: dict[str, Any], adjudication: dict[str, Any]) -> None:
    if adjudication["source_sha256"] != SOURCE_SHA:
        raise ValueError("10747 semantic adjudication source SHA drift")
    if adjudication["certification_state"] != "PASS":
        raise ValueError("10747 semantic adjudication is not PASS")
    items = {item["id"]: item for item in adjudication["adjudications"]}
    item = items.get("10747-SEM-001")
    if not item:
        raise ValueError("10747 Level-2 semantic adjudication missing")
    if (
        item["page"] != 15
        or item["frozen_table_id"] != "RTCR_NONPRASA_LEVEL2_IDENTITY"
        or item["corrected_semantic_scope"] != "PRASA_IDENTITY_REFERENCE"
        or item["row_count"] != 2
        or item["raw_pws_tokens"] != ["2672", "4945"]
        or item["state"] != "RESOLVED_SOURCE_STRUCTURE"
        or item["terminal_handling"] != "SUPERSEDE_LABEL_ONLY_PRESERVE_FROZEN_LEDGER"
    ):
        raise ValueError("10747 Level-2 semantic adjudication drift")
    table = next(
        (x for x in doc["reference_tables"] if x["table_id"] == item["frozen_table_id"]),
        None,
    )
    if table is None or len(table["rows"]) != item["row_count"]:
        raise ValueError("frozen Level-2 identity rows missing or changed")
    if [str(row[1]) for row in table["rows"]] != item["raw_pws_tokens"]:
        raise ValueError("Level-2 PWS token drift")
    effect = adjudication["arithmetic_effect"]
    if any(effect[k] != 0 for k in effect):
        raise ValueError("semantic label correction changed source arithmetic")


def _metric(doc: dict[str, Any], table: str, row: str, metric: str) -> tuple[int, int]:
    hits = [
        item
        for item in doc["violation_count_cells"]
        if item["table_id"] == table
        and item["row_label"] == row
        and item["metric_type"] == metric
    ]
    if len(hits) != 1:
        raise ValueError(f"expected exactly one metric: {table}/{row}/{metric}; got {len(hits)}")
    return hits[0]["violations"], hits[0]["systems"]


def validate_ledger(doc: dict[str, Any]) -> None:
    if doc["source_sha256"] != SOURCE_SHA or doc["source_pages"] != 40:
        raise ValueError("10747 source identity drift")

    if doc["page_arithmetic"] != {
        "source_pages": 40,
        "classified_pages": 40,
        "unresolved_pages": 0,
        "delta": 0,
    }:
        raise ValueError("10747 page arithmetic drift")

    table = doc["table_arithmetic"]
    expected = {
        "logical_table_regions": EXPECTED_TABLES,
        "header_blocks": EXPECTED_TABLES,
        "data_rows": EXPECTED_DATA_ROWS,
        "explicit_total_rows": EXPECTED_TOTAL_ROWS,
        "continuation_fragments": EXPECTED_CONTINUATIONS,
        "unresolved_table_regions": 0,
        "unresolved_rows": 0,
        "table_region_delta": 0,
        "logical_row_fragments_accounted": (
            EXPECTED_DATA_ROWS + EXPECTED_TOTAL_ROWS + EXPECTED_CONTINUATIONS
        ),
    }
    if table != expected:
        raise ValueError(f"10747 table arithmetic drift: {table}")

    metrics = doc["violation_count_cells"]
    if len(metrics) != EXPECTED_METRICS:
        raise ValueError(f"10747 metric denominator drift: {len(metrics)}")
    if doc["violation_metric_cell_arithmetic"] != {
        "metric_records": EXPECTED_METRICS,
        "unresolved_metric_records": 0,
        "delta": 0,
    }:
        raise ValueError("10747 metric arithmetic drift")

    forbidden_tables = {
        "1",
        "2",
        "23",
        "24",
        "RTCR_PRASA_LEVEL1_IDENTITY",
        "RTCR_NONPRASA_LEVEL2_IDENTITY",
        "RTCR_NONPRASA_SAMPLES",
    }
    for item in metrics:
        if item["table_id"] in forbidden_tables:
            raise ValueError("reference/compliance/exemption row leaked into violation denominator")
        for key in ("violations", "systems"):
            if not isinstance(item[key], int) or item[key] < 0:
                raise ValueError("invalid violation-count cell")
        if item["systems"] > item["violations"] and item["violations"] != 0:
            raise ValueError("systems exceed violation count")

    # Exact annual summary controls.
    if _metric(doc, "3B", "RTCR", "SUMMARY_MCL_TT") != (2, 2):
        raise ValueError("Table 3B RTCR source cell drift")
    if _metric(doc, "3B", "DBP - HAA5", "SUMMARY_MCL_TT") != (4, 2):
        raise ValueError("Table 3B HAA5 source cell drift")
    if _metric(doc, "19", "Haloacetic Acids", "MCL") != (5, 2):
        raise ValueError("Table 19 HAA5 source cell drift")

    # Repeated analyte rows are source representation, not additive event counts.
    patterns = {
        ("14", "MCL"): (29, (0, 0)),
        ("14", "MR"): (29, (1, 1)),
        ("15", "MCL"): (29, (0, 0)),
        ("15", "MR"): (29, (2, 2)),
        ("16", "MCL"): (21, (0, 0)),
        ("16", "MR"): (21, (0, 0)),
        ("17", "MCL"): (21, (0, 0)),
        ("17", "MR"): (21, (3, 3)),
    }
    for (table_id, metric_type), (count, pair) in patterns.items():
        rows = [
            item
            for item in metrics
            if item["table_id"] == table_id and item["metric_type"] == metric_type
        ]
        if len(rows) != count or any(
            (row["violations"], row["systems"]) != pair for row in rows
        ):
            raise ValueError(f"repeated-analyte source pattern drift: {table_id}/{metric_type}")

    findings = {item["id"]: item for item in doc["source_internal_findings"]}
    for contradiction_id in ("10747-CONTR-001", "10747-CONTR-002"):
        item = findings.get(contradiction_id)
        if (
            not item
            or item["state"] != "SOURCE_INTERNAL_CONTRADICTION"
            or item["terminal_handling"] != "PRESERVE_NO_REPAIR"
        ):
            raise ValueError(f"source contradiction was hidden or repaired: {contradiction_id}")
    nonadd = findings.get("10747-NONADDITIVE-001")
    if not nonadd or nonadd["terminal_handling"] != "DO_NOT_SUM_ANALYTE_ROWS":
        raise ValueError("non-additive source representation guard missing")

    exemptions = next(
        item for item in doc["reference_tables"] if item["table_id"] == "24"
    )
    if len(exemptions["rows"]) != 7:
        raise ValueError("Table 24 continuation was duplicated or lost")
    if len({row[1] for row in exemptions["rows"]}) != 7:
        raise ValueError("Table 24 PWSID denominator is not unique")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ledger",
        type=Path,
        nargs="?",
        default=Path("data/certification/prdoh_10747_structural_v1.json.gz.b64"),
    )
    parser.add_argument(
        "--semantic-adjudication",
        type=Path,
        default=Path("data/certification/prdoh_10747_semantic_adjudication_v1.json"),
    )
    args = parser.parse_args()
    doc = load_ledger(args.ledger)
    validate_ledger(doc)
    validate_semantic_adjudication(
        doc, load_semantic_adjudication(args.semantic_adjudication)
    )
    print("PRDOH_10747_STRUCTURAL_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
