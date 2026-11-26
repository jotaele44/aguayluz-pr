#!/usr/bin/env python3
"""Fail-closed validator for PRDOH 10746/10747/10748 internal reconciliation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RECEIPT = Path("data/certification/prdoh_internal_reconciliation_v1.json")
STRUCT_10748 = Path("data/certification/prdoh_10748_structural_v1.json")
SEM_10747 = Path("data/certification/prdoh_10747_semantic_adjudication_v1.json")

EXPECTED_SOURCES = {
    "10746": "3488ca04e0ad90106caaa568059ee574fa099c3854bf11a3930db372391ff1bd",
    "10747": "748529762de1b6661b5484957a7662bd233a37aaf371482cdc14bbf5ac584772",
    "10748": "9886fbed47e9f8a3564167034bedc6bc0a0d653c6f89d81d69f8101ccc3f2603",
}

EXPECTED_CHECK_IDS = {
    "PRASA-GWR-MR",
    "PRASA-TURBIDITY-43-TT",
    "PRASA-TURBIDITY-44-TT",
    "PRASA-CHLORINE-EQUIPMENT-MR",
    "PRASA-CHLORINE-SAMPLING-MR",
    "PRASA-LT2-TT",
    "PRASA-SOC-MR",
    "PRASA-TTHM-MCL",
    "PRASA-HAA5-MCL",
    "NONPRASA-NITRATE-MR",
    "NONPRASA-NITRITE-MR",
    "NONPRASA-IOC-SHARED-MR",
    "NONPRASA-VOC-MR",
    "NONPRASA-SOC-MR",
    "NONPRASA-TTHM-MR",
    "NONPRASA-HAA5-MCL-DETAIL",
    "NONPRASA-HAA5-MR",
    "NONPRASA-RTCR-MCL",
    "NONPRASA-RTCR-TT",
    "NONPRASA-RTCR-MR-COMMUNITY",
    "NONPRASA-RTCR-MR-NTNC",
    "NONPRASA-RTCR-MR-TNC",
    "NONPRASA-RTCR-MR-TOTAL",
    "NONPRASA-LCR-52-MR",
    "NONPRASA-LCR-57-TT",
    "NONPRASA-PUBLIC-NOTICE",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def bind_prdoh_pws_token(
    left_token: str,
    right_token: str,
    *,
    left_namespace: str,
    right_namespace: str,
) -> bool:
    """Only exact authority-issued token equality inside the same declared namespace binds."""
    return (
        left_namespace == right_namespace
        and left_namespace == "PRASA_PWS_4DIGIT"
        and len(left_token) == 4
        and left_token.isdigit()
        and left_token == right_token
    )


def validate_receipt(doc: dict[str, Any]) -> None:
    sources = doc["sources"]
    for source_id, expected_sha in EXPECTED_SOURCES.items():
        if sources[source_id]["sha256"] != expected_sha:
            raise ValueError(f"PRDOH source SHA drift: {source_id}")

    page = doc["source_page_arithmetic"]
    if page != {
        "source_pages": 74,
        "classified_or_frozen_pages": 74,
        "unresolved_pages": 0,
        "delta": 0,
    }:
        raise ValueError("PRDOH page arithmetic drift")

    fragments = doc["table_fragment_arithmetic"]
    combined = fragments["combined"]
    accounted = (
        combined["identity_bearing_rows"]
        + combined["violation_summary_or_detail_rows"]
        + combined["non_violation_reference_or_treatment_rows"]
        + combined["explicit_total_rows"]
        + combined["continuation_fragments"]
    )
    if combined["source_table_fragments"] != 585 or accounted != 585 or combined["delta"] != 0:
        raise ValueError("PRDOH table-fragment arithmetic failure")
    if fragments["10747"]["total_fragments"] != 224 or fragments["10748"]["total_fragments"] != 361:
        raise ValueError("PRDOH source fragment denominator drift")

    identity = doc["prasa_pws_token_identity"]
    if identity["state"] != "PASS":
        raise ValueError("PRDOH PWS token identity gate is not PASS")
    if identity["intersection"] != len(identity["intersection_tokens"]):
        raise ValueError("PWS intersection arithmetic failure")
    if identity["10747_only"] != len(identity["10747_only_tokens"]):
        raise ValueError("PWS 10747-only arithmetic failure")
    if identity["intersection"] + identity["10747_only"] != identity["10747_unique_tokens"]:
        raise ValueError("PWS 10747 set algebra failure")
    if identity["union"] != identity["intersection"] + identity["10747_only"] + identity["10748_only"]:
        raise ValueError("PWS union arithmetic failure")
    if identity["symmetric_difference"] != identity["10747_only"] + identity["10748_only"]:
        raise ValueError("PWS symmetric-difference arithmetic failure")
    if identity["intersection_tokens"] != ["2762", "4915", "4945", "5557"]:
        raise ValueError("PWS intersection token drift")
    if identity["unresolved_identity_tokens"] != 0:
        raise ValueError("unresolved PRDOH PWS identity residue")

    checks = {item["id"]: item for item in doc["exact_reconciliation_checks"]}
    if set(checks) != EXPECTED_CHECK_IDS:
        raise ValueError("PRDOH reconciliation check denominator drift")
    for item in checks.values():
        if not item["state"].startswith("PASS"):
            raise ValueError(f"non-PASS reconciliation check: {item['id']}")
        if item["report"] != item["annex"]:
            raise ValueError(f"report/annex mismatch outside declared contradiction: {item['id']}")

    # Independent arithmetic for the 1,268 RTCR MR denominator.
    community = checks["NONPRASA-RTCR-MR-COMMUNITY"]["annex"]
    ntnc = checks["NONPRASA-RTCR-MR-NTNC"]["annex"]
    tnc = checks["NONPRASA-RTCR-MR-TNC"]["annex"]
    total = checks["NONPRASA-RTCR-MR-TOTAL"]["annex"]
    if (
        community["violations"] + ntnc["violations"] + tnc["violations"] != total["violations"]
        or community["systems"] + ntnc["systems"] + tnc["systems"] != total["systems"]
        or total != {"violations": 1268, "systems": 121}
    ):
        raise ValueError("RTCR MR denominator arithmetic failure")

    scopes = doc["source_scope_adjudications"]
    if len(scopes) != 1:
        raise ValueError("unexpected scope-adjudication denominator")
    scope = scopes[0]
    if (
        scope["id"] != "PRDOH-SCOPE-001"
        or scope["state"] != "EXPLAINED_REPORTING_SCOPE_DIFFERENCE"
        or scope["terminal_handling"] != "PRESERVE_BOTH_NO_FORCED_EQUIVALENCE"
    ):
        raise ValueError("reporting-scope difference is not terminally adjudicated")

    contradictions = {x["id"]: x for x in doc["terminal_source_contradictions"]}
    if set(contradictions) != {"10747-CONTR-001", "10747-CONTR-002"}:
        raise ValueError("source contradiction denominator drift")
    for item in contradictions.values():
        if (
            item["state"] != "SOURCE_INTERNAL_CONTRADICTION"
            or item["terminal_handling"] != "PRESERVE_NO_REPAIR"
        ):
            raise ValueError(f"source contradiction hidden/repaired: {item['id']}")

    nonadd = doc["nonadditive_representation"]
    if (
        nonadd["id"] != "10747-NONADDITIVE-001"
        or nonadd["state"] != "EXPLAINED_SOURCE_REPRESENTATION"
    ):
        raise ValueError("non-additive source representation guard missing")

    for key in ("fail_count", "open_count", "blocked_count", "unresolved_count"):
        if doc[key] != 0:
            raise ValueError(f"material PRDOH residue remains: {key}={doc[key]}")
    if doc["unresolved_material"]:
        raise ValueError("unresolved_material must be empty")
    if doc["reconciliation_state"] != "PASS":
        raise ValueError("PRDOH internal reconciliation is not PASS")
    if "SDWIS" not in doc["downstream_gate"] or "prohibited" not in doc["downstream_gate"]:
        raise ValueError("downstream PRDOH→SDWIS gate missing")


def validate_bound_sources(doc: dict[str, Any], receipt_10748: dict[str, Any], sem_10747: dict[str, Any]) -> None:
    if receipt_10748["source_sha256"] != doc["sources"]["10748"]["sha256"]:
        raise ValueError("10748 receipt/source mismatch")
    if receipt_10748["certification_state"] != "PRDOH_10748_STRUCTURAL_CERTIFIED":
        raise ValueError("10748 structural certificate not present")
    if sem_10747["source_sha256"] != doc["sources"]["10747"]["sha256"]:
        raise ValueError("10747 semantic/source mismatch")
    if sem_10747["certification_state"] != "PASS":
        raise ValueError("10747 semantic adjudication not PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", nargs="?", type=Path, default=RECEIPT)
    parser.add_argument("--receipt-10748", type=Path, default=STRUCT_10748)
    parser.add_argument("--semantic-10747", type=Path, default=SEM_10747)
    args = parser.parse_args()
    doc = load_json(args.receipt)
    validate_receipt(doc)
    validate_bound_sources(
        doc,
        load_json(args.receipt_10748),
        load_json(args.semantic_10747),
    )
    print("PRDOH_INTERNAL_RECONCILIATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
