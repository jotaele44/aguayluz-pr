"""End-to-end test for `scripts/run_full_chain.py`.

Runs the full M5→M15 chain in demo mode and asserts the 9 expected entity
files exist, validate, and carry sane content. Live mode is exercised
manually via the `.github/workflows/live-corpus.yml` workflow_dispatch.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_OUTPUTS = (
    "utility_assets.json",
    "service_events.json",
    "source_manifest.json",
    "review_queue.json",
    "integration_report.json",
    "dependency_graph.json",
    "bridge_summary.json",
    "reconciliation_report.json",
    "watershed_delineation.json",
    "base44_export.json",
)


def _run_chain(outputs_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_full_chain.py"),
            "--outputs-dir", str(outputs_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


def test_demo_chain_exits_zero(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    proc = _run_chain(outputs)
    assert proc.returncode == 0, f"chain failed:\n{proc.stderr}"


def test_demo_chain_writes_full_output_set(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    proc = _run_chain(outputs)
    assert proc.returncode == 0, proc.stderr
    missing = [name for name in EXPECTED_OUTPUTS if not (outputs / name).exists()]
    assert not missing, f"missing outputs after chain: {missing}"


def test_demo_chain_envelope_status_pass(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    proc = _run_chain(outputs)
    assert proc.returncode == 0, proc.stderr
    envelope = json.loads((outputs / "base44_export.json").read_text())
    assert envelope["status"] == "PASS"
    assert envelope["records_total"] > 0


def test_demo_chain_produces_non_empty_graph_and_findings(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    proc = _run_chain(outputs)
    assert proc.returncode == 0, proc.stderr
    graph = json.loads((outputs / "dependency_graph.json").read_text())
    recon = json.loads((outputs / "reconciliation_report.json").read_text())
    assert graph["edges"], "dependency_graph should have at least one edge from demo data"
    assert recon["findings"], "reconciliation should have at least one finding"


def test_chain_summary_in_stdout(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    proc = _run_chain(outputs)
    assert proc.returncode == 0, proc.stderr
    assert "=== chain summary ===" in proc.stdout
    assert "assets_total:" in proc.stdout
    assert "envelope_status: PASS" in proc.stdout
