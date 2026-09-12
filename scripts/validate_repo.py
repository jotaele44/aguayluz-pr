#!/usr/bin/env python3
"""Run AguaYLuz validation gates in audit or strict certification mode.

Default mode preserves the operator-facing readiness audit. ``--certification``
is intentionally stricter: every configured gate must be PASS, an executed-test
receipt bound to the current Git commit must be supplied, and the federation
spatial manifest must itself pass its fail-closed certification validator.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = REPO_ROOT / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.validation import assert_schemas_resolvable, run_gates  # noqa: E402

HEX40 = re.compile(r"^[0-9a-f]{40}$")
TEST_RECEIPT_SCHEMA = "aguayluz_test_execution_receipt_v1"


def _payload(report, *, certification: bool = False) -> dict[str, object]:
    gates = [
        {"gate_id": gate_id, "status": status, "details": details}
        for gate_id, status, details in report.as_rows()
    ]
    if certification:
        blocking_failures = [gate for gate in gates if gate["status"] != "PASS"]
    else:
        blocking_failures = [r for r in report.results if r.is_blocking_failure]
    return {
        "mode": "CERTIFICATION" if certification else "AUDIT",
        "status": "FAIL" if blocking_failures else "PASS",
        "blocking_failure_count": len(blocking_failures),
        "gates": gates,
    }


def _current_git_identity() -> tuple[str, str]:
    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    commit_sha = run("rev-parse", "HEAD")
    tree_sha = run("rev-parse", "HEAD^{tree}")
    if not HEX40.fullmatch(commit_sha) or not HEX40.fullmatch(tree_sha):
        raise ValueError("unable to establish 40-character Git commit/tree identity")
    return commit_sha, tree_sha


def _validate_test_receipt(path: Path | None) -> dict[str, str]:
    gate_id = "G08_EXECUTED_TEST_RECEIPT"
    if path is None:
        return {"gate_id": gate_id, "status": "FAIL", "details": "--test-receipt is required in certification mode"}
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - fail closed
        return {"gate_id": gate_id, "status": "FAIL", "details": f"invalid test receipt: {exc}"}
    if not isinstance(receipt, dict):
        return {"gate_id": gate_id, "status": "FAIL", "details": "test receipt root must be an object"}
    if receipt.get("schema_version") != TEST_RECEIPT_SCHEMA:
        return {"gate_id": gate_id, "status": "FAIL", "details": "unsupported test receipt schema"}
    if receipt.get("status") != "PASS":
        return {"gate_id": gate_id, "status": "FAIL", "details": f"test receipt status is {receipt.get('status')!r}"}
    if receipt.get("suite") != "FULL":
        return {"gate_id": gate_id, "status": "FAIL", "details": "test receipt suite must be FULL"}
    command = receipt.get("command")
    if not isinstance(command, str) or "pytest" not in command:
        return {"gate_id": gate_id, "status": "FAIL", "details": "test receipt command must identify pytest execution"}
    try:
        commit_sha, tree_sha = _current_git_identity()
    except Exception as exc:  # noqa: BLE001
        return {"gate_id": gate_id, "status": "FAIL", "details": f"cannot bind receipt to current Git identity: {exc}"}
    if receipt.get("commit_sha") != commit_sha:
        return {"gate_id": gate_id, "status": "FAIL", "details": "test receipt commit_sha does not match current HEAD"}
    if receipt.get("tree_sha") != tree_sha:
        return {"gate_id": gate_id, "status": "FAIL", "details": "test receipt tree_sha does not match current HEAD tree"}
    return {"gate_id": gate_id, "status": "PASS", "details": f"FULL pytest receipt bound to {commit_sha}"}


def _validate_spatial_certification() -> dict[str, str]:
    gate_id = "G09_SPATIAL_CERTIFICATION"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_federation_spatial.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (proc.stdout or proc.stderr).strip()
    if len(detail) > 500:
        detail = detail[:500] + "…"
    return {
        "gate_id": gate_id,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "details": detail or f"spatial validator exited {proc.returncode}",
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AguaYLuz repository validation gates.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--certification",
        action="store_true",
        help="require PASS for every gate plus current-commit test and spatial certification evidence",
    )
    parser.add_argument("--test-receipt", type=Path, help="FULL pytest execution receipt for certification mode")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.test_receipt is not None and not args.certification:
        print("FAIL — --test-receipt is only valid with --certification", file=sys.stderr)
        return 2

    try:
        assert_schemas_resolvable()
        report = run_gates()
        payload = _payload(report, certification=args.certification)
        if args.certification:
            supplemental = [
                _validate_test_receipt(args.test_receipt),
                _validate_spatial_certification(),
            ]
            payload["gates"].extend(supplemental)  # type: ignore[union-attr]
            extra_failures = sum(1 for gate in supplemental if gate["status"] != "PASS")
            payload["blocking_failure_count"] = int(payload["blocking_failure_count"]) + extra_failures
            payload["status"] = "FAIL" if payload["blocking_failure_count"] else "PASS"
    except Exception as exc:  # fail closed for manager/CI callers
        payload = {
            "mode": "CERTIFICATION" if args.certification else "AUDIT",
            "status": "FAIL",
            "blocking_failure_count": 1,
            "gates": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"FAIL — {payload['error']}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        gates: list[dict[str, Any]] = payload["gates"]  # type: ignore[assignment]
        width_id = max(len(str(row["gate_id"])) for row in gates)
        width_status = max(len(str(row["status"])) for row in gates)
        print(f"\n{'GATE'.ljust(width_id)}  {'STATUS'.ljust(width_status)}  DETAILS")
        print(f"{'-' * width_id}  {'-' * width_status}  -------")
        for row in gates:
            print(
                f"{str(row['gate_id']).ljust(width_id)}  "
                f"{str(row['status']).ljust(width_status)}  {row['details']}"
            )
        print()
        if payload["status"] == "FAIL":
            print(f"FAIL — {payload['blocking_failure_count']} blocking gate(s) failed.")
        else:
            print("PASS — every gate required by this mode passed.")

    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
