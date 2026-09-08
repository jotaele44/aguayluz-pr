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
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "validate_unified_skillpacks.py"),
                "--root",
                str(ROOT),
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

    def test_spatial_architecture_allowlist_is_exact(self) -> None:
        manifest = json.loads((ROOT / ".claude/skillpacks/MANIFEST.json").read_text())
        allowed = manifest["allowed_change_paths"]
        intended = {
            "docs/SPATIAL_RESPONSIBILITY_V1.md",
            "schemas/federation_spatial_identity_v1_1.schema.json",
            "schemas/federation_spatial_migration_receipt_v1_1.schema.json",
            "scripts/federation_spatial_binding_v1_1.py",
            "tests/test_federation_spatial_binding_v1_1.py",
            "tests/test_schemas.py",
        }
        self.assertTrue(intended.issubset(allowed))
        for near_miss in (
            "docs/SPATIAL_RESPONSIBILITY_V1.md.bak",
            "schemas/federation_spatial_identity_v1_1.schema.json/extra",
            "scripts/federation_spatial_binding_v1_1.pyc",
            "tests/test_federation_spatial_binding_v1_1.py.bak",
            "tests/test_schemas.py.bak",
        ):
            self.assertFalse(MODULE.is_allowed_path(near_miss, allowed), near_miss)


if __name__ == "__main__":
    unittest.main()
