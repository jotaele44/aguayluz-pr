#!/usr/bin/env python3
"""Run the federation validation gates and report PASS/WARN/FAIL/SKIP.

``--json`` exposes the existing validation surface to TheHub's typed GUI action
without introducing a second CLI framework/discovery identity.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as `python scripts/validate_repo.py` from the repo root even
# without an editable install — useful for iOS a-Shell and CI bootstrap.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.validation import assert_schemas_resolvable, run_gates  # noqa: E402


def _payload(report) -> dict[str, object]:
    rows = report.as_rows()
    blocking_failures = [r for r in report.results if r.is_blocking_failure]
    return {
        "status": "FAIL" if blocking_failures else "PASS",
        "blocking_failure_count": len(blocking_failures),
        "gates": [
            {"gate_id": gate_id, "status": status, "details": details}
            for gate_id, status, details in rows
        ],
    }


def _parse_args(argv: list[str]) -> bool:
    json_output = False
    for token in argv:
        if token == "--json":
            json_output = True
        else:
            raise ValueError(f"unknown argument: {token}")
    return json_output


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    try:
        json_output = _parse_args(raw_args)
    except ValueError as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 2

    try:
        assert_schemas_resolvable()
        report = run_gates()
        payload = _payload(report)
    except Exception as exc:  # fail closed for manager/CI callers
        payload = {
            "status": "FAIL",
            "blocking_failure_count": 1,
            "gates": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
        if json_output:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"FAIL — {payload['error']}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(payload, sort_keys=True))
    else:
        rows = report.as_rows()
        width_id = max(len(r[0]) for r in rows)
        width_status = max(len(r[1]) for r in rows)
        print(f"\n{'GATE'.ljust(width_id)}  {'STATUS'.ljust(width_status)}  DETAILS")
        print(f"{'-' * width_id}  {'-' * width_status}  -------")
        for gate_id, status, details in rows:
            print(f"{gate_id.ljust(width_id)}  {status.ljust(width_status)}  {details}")

        print()
        if payload["status"] == "FAIL":
            print(f"FAIL — {payload['blocking_failure_count']} blocking gate(s) failed.")
        else:
            print("OK — no blocking gate failures.")

    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
