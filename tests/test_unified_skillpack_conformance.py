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

FLIGHT_TELEMETRY_PATHS = (
    ".federation/flight_telemetry_binding.json",
    ".federation/flight_telemetry_contract.json",
    ".github/workflows/flight-telemetry-contract.yml",
    "scripts/discover_flight_provider_capabilities.py",
    "scripts/validate_flight_telemetry_contract.py",
    "scripts/validate_flight_telemetry_federation_lockstep.py",
)
FLIGHT_TELEMETRY_NEAR_MISSES = (
    ".federation/",
    ".federation/flight_telemetry_binding.json.bak",
    ".github/workflows/flight-telemetry-contract.yml.disabled",
    "scripts/",
    "scripts/validate_flight_telemetry_contract.py.backup",
)


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

    def test_flight_telemetry_scope_is_exact(self) -> None:
        manifest = json.loads((ROOT / ".claude/skillpacks/MANIFEST.json").read_text())
        allowed_paths = manifest["allowed_change_paths"]
        for file_path in FLIGHT_TELEMETRY_PATHS:
            self.assertIn(file_path, allowed_paths)
            self.assertTrue(MODULE.is_allowed_path(file_path, allowed_paths))
        for file_path in FLIGHT_TELEMETRY_NEAR_MISSES:
            self.assertNotIn(file_path, allowed_paths)
            self.assertFalse(MODULE.is_allowed_path(file_path, allowed_paths))


if __name__ == "__main__":
    unittest.main()
