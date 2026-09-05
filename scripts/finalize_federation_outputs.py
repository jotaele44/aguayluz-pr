#!/usr/bin/env python3
"""Finalize generated outputs with post-generation gate state.

The exporter necessarily creates hub_export/integration_report after an initial
bootstrap gate pass in which G05/G06 are absent. This finalizer reruns the gates
only after the complete output set exists, replaces the bootstrap ledger, and
requires an executed FULL pytest receipt for G08. It prevents a bootstrap SKIP
from being serialized as a certification-like PASS.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from aguayluz.models import validate_against_schema
from aguayluz.validation import run_gates

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def _load_repo_validator():
    path = ROOT / "scripts" / "validate_repo.py"
    spec = importlib.util.spec_from_file_location("aguayluz_validate_repo", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/validate_repo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strict_aggregate(statuses: list[str]) -> str:
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    if any(status == "SKIP" for status in statuses):
        return "BLOCKED"
    if any(status == "WARN" for status in statuses):
        return "WARN"
    return "PASS"


def finalize(test_receipt: Path) -> dict[str, object]:
    integration_path = OUTPUTS / "integration_report.json"
    hub_path = OUTPUTS / "hub_export.json"
    if not integration_path.is_file() or not hub_path.is_file():
        raise FileNotFoundError("complete outputs/ set is required before finalization")

    report = run_gates()
    receipt_gate = _load_repo_validator()._validate_test_receipt(test_receipt)
    rows: list[dict[str, object]] = []
    for result in report.results:
        status = result.status
        details = result.details or None
        if result.gate_id == "G08_TESTS":
            status = receipt_gate["status"]
            details = receipt_gate["details"]
        rows.append({"id": result.gate_id, "status": status, "details": details})

    statuses = [str(row["status"]) for row in rows]
    aggregate = _strict_aggregate(statuses)

    integration = json.loads(integration_path.read_text(encoding="utf-8"))
    hub_export = json.loads(hub_path.read_text(encoding="utf-8"))
    integration["gates"] = rows
    hub_export["status"] = aggregate

    validate_against_schema("integration_report", integration)
    validate_against_schema("hub_export", hub_export)
    integration_path.write_text(json.dumps(integration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    hub_path.write_text(json.dumps(hub_export, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Re-read the two finalized files through the normal gates. All non-test
    # gates must now PASS; G08 is represented by the bound execution receipt.
    post = run_gates()
    post_nonpass = [
        f"{result.gate_id}={result.status}"
        for result in post.results
        if result.gate_id != "G08_TESTS" and result.status != "PASS"
    ]
    problems: list[str] = []
    if post_nonpass:
        problems.append(f"post-finalization non-PASS gates: {post_nonpass}")
    if receipt_gate["status"] != "PASS":
        problems.append(str(receipt_gate["details"]))
    if aggregate != "PASS":
        problems.append(f"final aggregate status is {aggregate}")

    return {
        "ok": not problems,
        "aggregate_status": aggregate,
        "gate_statuses": {str(row["id"]): str(row["status"]) for row in rows},
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = finalize(args.test_receipt)
    except Exception as exc:  # noqa: BLE001 - fail closed
        result = {"ok": False, "aggregate_status": "FAIL", "problems": [f"{type(exc).__name__}: {exc}"]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
