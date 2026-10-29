"""Adversarial tests for canonical GUI reference-data staging."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "server" / "ingestion" / "stage_gui_reference_data.py"
SOURCE_NAMES = (
    "cave_karst_assets.jsonl",
    "nwps_gauge_state.jsonl",
    "hydromet_receipts.json",
    "hydromet_manifestations.jsonl",
)
RECEIPT_NAME = ".gui-reference-staging.json"


class GuiReferenceStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aguayluz-gui-parity-test-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)

    def run_stage(self, workspace: Path | None = None, *, remove_home: bool = False):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if remove_home:
            env.pop("AGUAYLUZ_DATA_HOME", None)
        else:
            env["AGUAYLUZ_DATA_HOME"] = str(workspace or self.workspace)
        return subprocess.run(
            [sys.executable, str(STAGER)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_stages_exact_allowlist_with_hash_parity(self):
        result = self.run_stage()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = self.workspace / "data"
        self.assertEqual(
            {path.name for path in data.iterdir()},
            set(SOURCE_NAMES) | {RECEIPT_NAME},
        )
        receipt = json.loads((data / RECEIPT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], "aguayluz.gui-reference-staging/v1")
        self.assertEqual(receipt["authority_head"], subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip())
        self.assertEqual(
            {entry["path"] for entry in receipt["files"]},
            {f"data/{name}" for name in SOURCE_NAMES},
        )
        for entry in receipt["files"]:
            source = ROOT / entry["path"]
            staged = data / source.name
            self.assertEqual(source.read_bytes(), staged.read_bytes())
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(entry["source_sha256"], digest)
            self.assertEqual(entry["staged_sha256"], digest)
            self.assertEqual(entry["bytes"], len(source.read_bytes()))
            expected_blob = subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", f"HEAD:{entry['path']}"],
                text=True,
            ).strip()
            self.assertEqual(entry["git_blob_sha"], expected_blob)

    def test_repeated_staging_is_idempotent(self):
        first = self.run_stage()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        data = self.workspace / "data"
        before = {p.name: p.read_bytes() for p in data.iterdir()}
        second = self.run_stage()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        after = {p.name: p.read_bytes() for p in data.iterdir()}
        self.assertEqual(before, after)

    def test_missing_workspace_is_rejected(self):
        result = self.run_stage(remove_home=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AGUAYLUZ_DATA_HOME is required", result.stderr)

    def test_workspace_without_owned_prefix_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="not-gui-parity-") as raw:
            result = self.run_stage(Path(raw))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ownership prefix", result.stderr)

    def test_unexpected_data_entry_fails_before_staging(self):
        data = self.workspace / "data"
        data.mkdir()
        unexpected = data / "operator.json"
        unexpected.write_text('{"preserve":true}', encoding="utf-8")
        result = self.run_stage()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(unexpected.read_text(encoding="utf-8"), '{"preserve":true}')
        self.assertEqual({p.name for p in data.iterdir()}, {"operator.json"})

    def test_conflicting_existing_reference_is_never_overwritten(self):
        data = self.workspace / "data"
        data.mkdir()
        target = data / "cave_karst_assets.jsonl"
        target.write_bytes(b"operator-owned")
        result = self.run_stage()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), b"operator-owned")
        self.assertEqual({p.name for p in data.iterdir()}, {target.name})

    def test_tampered_staged_file_fails_closed_and_is_preserved(self):
        result = self.run_stage()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        target = self.workspace / "data" / "nwps_gauge_state.jsonl"
        target.write_bytes(b"tampered")
        result = self.run_stage()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), b"tampered")

    def test_symlink_destination_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory(prefix="operator-data-") as outside:
            protected = Path(outside) / "protected.jsonl"
            protected.write_bytes(b"operator-owned")
            data = self.workspace / "data"
            data.mkdir()
            (data / "cave_karst_assets.jsonl").symlink_to(protected)
            result = self.run_stage()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(protected.read_bytes(), b"operator-owned")

    def test_conflicting_receipt_is_not_replaced(self):
        result = self.run_stage()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = self.workspace / "data" / RECEIPT_NAME
        receipt.write_text('{"stale":true}\n', encoding="utf-8")
        result = self.run_stage()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt.read_text(encoding="utf-8"), '{"stale":true}\n')

    def test_concurrent_staging_is_serialized_or_idempotent(self):
        env = os.environ.copy()
        env["AGUAYLUZ_DATA_HOME"] = str(self.workspace)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, str(STAGER)]
        first = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out1, err1 = first.communicate(timeout=30)
        out2, err2 = second.communicate(timeout=30)
        self.assertIn(first.returncode, (0, 2), out1 + err1)
        self.assertIn(second.returncode, (0, 2), out2 + err2)
        self.assertTrue(first.returncode == 0 or second.returncode == 0, out1 + err1 + out2 + err2)
        final = self.run_stage()
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

    def test_unlocked_stale_lock_file_allows_crash_recovery(self):
        (self.workspace / ".gui-reference-staging.lock").touch()
        result = self.run_stage()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
