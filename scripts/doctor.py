#!/usr/bin/env python3
"""Run this repo's declared external-dependency checks and report PASS/WARN/FAIL/SKIP/INFO.

Reads `.federation/doctor-checks.json` and `federation.json`, and delegates
to the shared `prii_doctor` engine. Unlike `scripts/validate_repo.py` (which
this tool's `outputs_schema_validation` check itself delegates to), this
covers the checks validate_repo.py structurally cannot: credential
*presence* (never validity), WAF-gated and manually-sourced upstream data,
and doc-vs-manifest drift. See `.federation/doctor-checks.json` for the
per-check rationale and `packages/prii_doctor/README.md` (thehub-pr) for the
design this tool is built on.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        from prii_doctor import print_table, run
    except ImportError:
        print(
            "prii-doctor is not installed. Run `pip install -e .[dev]` "
            "(it is declared in pyproject.toml's [tool.uv.sources])."
        )
        return 1

    report = run(_REPO_ROOT)
    print_table(report)
    return 0 if report.all_blocking_passed else 1


if __name__ == "__main__":
    sys.exit(main())
