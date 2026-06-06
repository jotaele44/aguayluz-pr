#!/usr/bin/env python3
"""Run the eight federation validation gates and report PASS/WARN/FAIL/SKIP."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python scripts/validate_repo.py` from the repo root even
# without an editable install — useful for iOS a-Shell and CI bootstrap.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.validation import assert_schemas_resolvable, run_gates  # noqa: E402


def main() -> int:
    assert_schemas_resolvable()
    report = run_gates()

    rows = report.as_rows()
    width_id = max(len(r[0]) for r in rows)
    width_status = max(len(r[1]) for r in rows)
    print(f"\n{'GATE'.ljust(width_id)}  {'STATUS'.ljust(width_status)}  DETAILS")
    print(f"{'-' * width_id}  {'-' * width_status}  -------")
    for gate_id, status, details in rows:
        print(f"{gate_id.ljust(width_id)}  {status.ljust(width_status)}  {details}")

    blocking_failures = [r for r in report.results if r.is_blocking_failure]
    print()
    if blocking_failures:
        print(f"FAIL — {len(blocking_failures)} blocking gate(s) failed.")
        return 1
    print("OK — no blocking gate failures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
