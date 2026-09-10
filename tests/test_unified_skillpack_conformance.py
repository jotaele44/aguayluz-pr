from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_unified_skillpacks", ROOT / "tools" / "validate_unified_skillpacks.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class TestUnifiedSkillpackConformance(unittest.TestCase):
    def test_conformance(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                str(repository_root / "tools" / "validate_unified_skillpacks.py"),
                "--root",
                str(repository_root),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + "\n" + result.stderr,
        )

    def test_change_scope_can_use_current_integration_base(self) -> None:
        head = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        result = MODULE.validate(ROOT, enforce_change_scope=True, change_base=head)
        self.assertEqual(result["status"], "success", result["errors"])
        self.assertIn("change_base_ancestry", result["checks"])


if __name__ == "__main__":
    unittest.main()
