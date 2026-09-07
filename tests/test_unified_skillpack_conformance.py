from __future__ import annotations

import importlib.util
import json
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

    def test_spatial_scope_remains_exact(self) -> None:
        manifest = json.loads((ROOT / ".claude/skillpacks/MANIFEST.json").read_text())
        allowed = manifest["allowed_change_paths"]
        self.assertTrue(MODULE.is_allowed_path("federation/spatial/grid_manifest.json", allowed))
        self.assertFalse(MODULE.is_allowed_path("federation/spatial/unreviewed.json", allowed))
        self.assertFalse(MODULE.is_allowed_path("governance/unreviewed.json", allowed))


if __name__ == "__main__":
    unittest.main()
