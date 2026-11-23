#!/usr/bin/env python3
"""Fail-closed validator for the frozen PRDOH 10748 structural receipt."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PWSID_RE = re.compile(r"^PR\d{7}$")
IDENTITY_CLASSES = {"IDENTITY_TABLE", "VIOLATION_TABLE", "SYSTEM_TABLE"}


def same_system(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Bind only when both sides carry the same stable normalized PWSID."""
    a = left.get("pwsid")
    b = right.get("pwsid")
    return bool(PWSID_RE.fullmatch(str(a or "")) and a == b)


def admit_to_violation_denominator(region_class: str) -> bool:
    return region_class in {"IDENTITY_TABLE", "VIOLATION_TABLE"}


def enforce_join_conservation(before: int, expected_multiplier: int, after: int) -> None:
    expected = before * expected_multiplier
    if after != expected:
        raise ValueError(f"join conservation failure: {before}*{expected_multiplier}={expected} != {after}")


def validate_receipt(doc: dict[str, Any]) -> None:
    if doc["source_sha256"] != "9886fbed47e9f8a3564167034bedc6bc0a0d653c6f89d81d69f8101ccc3f2603":
        raise ValueError("source SHA drift")
    page = doc["page_arithmetic"]
    if page != {"source_pages": 33, "classified_pages": 33, "unresolved_pages": 0, "delta": 0}:
        raise ValueError(f"page arithmetic drift: {page}")
    row = doc["row_arithmetic"]
    accounted = (
        row["identity_bearing_rows"]
        + row["excluded_reference_rows"]
        + row["excluded_treatment_rows"]
        + row["excluded_continuation_fragments"]
        + row["unresolved_row_fragments"]
    )
    if accounted != row["visible_table_row_fragments"] or row["delta"] != 0:
        raise ValueError("row arithmetic not conserved")
    if row["identity_bearing_rows"] != row["violation_enforcement_rows"] + row["system_rows"]:
        raise ValueError("identity-bearing arithmetic not conserved")
    if row["violation_enforcement_rows"] != 129 or row["system_rows"] != 121:
        raise ValueError("identity denominator drift")
    fw = doc["reference_treatment_firewall"]
    if any(
        fw[k] != 0
        for k in (
            "reference_rows_admitted_to_violation_denominator",
            "treatment_rows_admitted_to_violation_denominator",
            "continuation_fragments_admitted_as_new_rows",
        )
    ):
        raise ValueError("reference/treatment firewall failure")
    if fw["state"] != "PASS":
        raise ValueError("firewall is not PASS")
    graph = doc["identity_candidate_graph"]
    if graph["intersection"] + graph["violation_only"] != graph["violation_unique_pwsids"]:
        raise ValueError("violation set algebra failure")
    if graph["intersection"] + graph["system_only"] != graph["system_unique_pwsids"]:
        raise ValueError("system set algebra failure")
    if graph["union"] != graph["intersection"] + graph["violation_only"] + graph["system_only"]:
        raise ValueError("union arithmetic failure")
    if graph["symmetric_difference"] != graph["violation_only"] + graph["system_only"]:
        raise ValueError("symmetric-difference arithmetic failure")
    if sorted(graph["intersection_pwsids"]) != sorted(set(graph["intersection_pwsids"])):
        raise ValueError("duplicate intersection PWSID")
    if not all(PWSID_RE.fullmatch(x) for x in graph["intersection_pwsids"]):
        raise ValueError("malformed intersection PWSID")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("receipt", type=Path)
    args = p.parse_args()
    doc = json.loads(args.receipt.read_text(encoding="utf-8"))
    validate_receipt(doc)
    print("PRDOH_10748_STRUCTURAL_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
