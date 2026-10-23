"""Bounded adversarial regression for GUI parity fixture ownership.

Each case runs against disposable external data homes, never operator outputs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "server/ingestion/seed_demo.py"
TEARDOWN = ROOT / "server/ingestion/gui_parity_teardown.py"


class FixtureIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ayl-fixture-test-")
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.exports = self.home / "exports"
        self.queue = self.exports / "review_queue.json"
        self.marker = self.exports / ".review_queue.seeded"
        self.run_id = "test-" + self.home.name

    def invoke(self, script: Path, home: Path | None = None, run_id: str | None = None):
        env = os.environ.copy()
        env["AGUAYLUZ_DATA_HOME"] = str(home or self.home)
        env["AGUAYLUZ_GUI_PARITY_RUN_ID"] = run_id or self.run_id
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT, env=env, capture_output=True,
            text=True, timeout=20,
        )

    def test_normal_seed_and_cleanup(self):
        self.assertEqual(self.invoke(SEED).returncode, 0)
        self.assertTrue(self.queue.exists())
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.invoke(TEARDOWN).returncode, 0)
        self.assertFalse(self.queue.exists())
        self.assertFalse(self.marker.exists())

    def test_operator_data_without_marker_preserved(self):
        self.exports.mkdir()
        self.queue.write_text('{"origin":"operator"}', encoding="utf-8")
        self.assertEqual(self.invoke(TEARDOWN).returncode, 0)
        self.assertEqual(self.queue.read_text(), '{"origin":"operator"}')
        self.assertNotEqual(self.invoke(SEED).returncode, 0)

    def test_stale_marker_cannot_delete_replaced_export(self):
        self.assertEqual(self.invoke(SEED).returncode, 0)
        replacement = '{"origin":"operator","records":[1,2]}'
        self.queue.write_text(replacement, encoding="utf-8")
        result = self.invoke(TEARDOWN)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.queue.read_text(encoding="utf-8"), replacement)
        self.assertTrue(self.marker.exists())

    def test_cleanup_failure_must_be_nonzero(self):
        self.assertEqual(self.invoke(SEED).returncode, 0)
        self.queue.unlink()
        self.queue.mkdir()
        self.assertNotEqual(self.invoke(TEARDOWN).returncode, 0)
        self.assertTrue(self.marker.exists())

    def test_wrong_run_id_cannot_delete_fixture(self):
        self.assertEqual(self.invoke(SEED).returncode, 0)
        self.assertNotEqual(
            self.invoke(TEARDOWN, run_id="different-run").returncode, 0,
        )
        self.assertTrue(self.queue.exists())
        self.assertEqual(self.invoke(TEARDOWN).returncode, 0)

    def test_corrupt_marker_preserves_queue(self):
        self.assertEqual(self.invoke(SEED).returncode, 0)
        self.marker.write_text("not json", encoding="utf-8")
        self.assertNotEqual(self.invoke(TEARDOWN).returncode, 0)
        self.assertTrue(self.queue.exists())

    def test_crash_before_marker_fails_closed(self):
        self.exports.mkdir()
        self.queue.write_text('{"total":3,"items":[{"record_ref":"SEED-1"}]}')
        self.assertNotEqual(self.invoke(SEED).returncode, 0)
        self.assertEqual(self.invoke(TEARDOWN).returncode, 0)
        self.assertTrue(self.queue.exists())  # no ownership -> do not delete

    def test_parallel_independent_workspaces(self):
        sibling = self.home / "second"
        sibling.mkdir()
        self.assertEqual(self.invoke(SEED).returncode, 0)
        self.assertEqual(self.invoke(SEED, sibling, "second-run").returncode, 0)
        self.assertEqual(self.invoke(TEARDOWN).returncode, 0)
        self.assertTrue((sibling / "exports/review_queue.json").exists())
        self.assertEqual(self.invoke(TEARDOWN, sibling, "second-run").returncode, 0)
        self.assertFalse((sibling / "exports/review_queue.json").exists())

    def test_invalid_workspace_is_rejected(self):
        env = os.environ.copy()
        env.pop("AGUAYLUZ_DATA_HOME", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        for script in (SEED, TEARDOWN):
            p = subprocess.run(
                [sys.executable, str(script)],
                cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
