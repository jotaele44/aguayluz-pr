"""Drift guard for `docs/gap_analysis.md`.

Re-runs `scripts/gap_audit.py --check` to verify the committed counts block
matches the live audit. Fails if any PR adds/removes a schema, CLI
subcommand, script, test file, or ingest adapter without regenerating the
gap analysis.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_gap_audit_check_passes():
    """The committed docs/gap_analysis.md is in sync with the live audit."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gap_audit.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode == 0, (
        "docs/gap_analysis.md counts are stale. "
        "Run `python scripts/gap_audit.py` and commit.\n"
        f"stderr:\n{proc.stderr}"
    )
