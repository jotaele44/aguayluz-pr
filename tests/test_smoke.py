"""End-to-end smoke test.

Demo-mode is unconditional. Live mode is gated by EPA_WATERS_API_KEY and only
runs when the key is set — CI without a key auto-skips.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_smoke(outputs_dir: Path, demo_mode: bool = True) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(REPO_ROOT / "scripts" / "smoke_test.py")]
    if demo_mode:
        args.append("--demo-mode")
    args += ["--outputs-dir", str(outputs_dir)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


# ---------- demo mode ----------


def test_smoke_demo_mode_exit_zero(tmp_path):
    outputs = tmp_path / "outputs"
    proc = _run_smoke(outputs, demo_mode=True)
    assert proc.returncode == 0, proc.stderr
    line = proc.stdout.strip().splitlines()[-1]
    assert "COMID=21000100" in line
    assert "reachcode=21010002000001" in line
    assert "VPU=21" in line
    assert "attribute_coverage=partial" in line


def test_smoke_demo_mode_writes_all_outputs(tmp_path):
    outputs = tmp_path / "outputs"
    proc = _run_smoke(outputs, demo_mode=True)
    assert proc.returncode == 0, proc.stderr

    expected = {
        "utility_assets.json", "service_events.json", "source_manifest.json",
        "review_queue.json", "integration_report.json", "base44_export.json",
    }
    produced = {p.name for p in outputs.iterdir() if p.suffix == ".json"}
    assert expected <= produced, f"missing: {expected - produced}"


def test_smoke_demo_mode_outputs_validate(tmp_path):
    outputs = tmp_path / "outputs"
    proc = _run_smoke(outputs, demo_mode=True)
    assert proc.returncode == 0, proc.stderr

    # Re-validate the produced files against their schemas — same contract the
    # gates enforce. This catches drift between the smoke writer and the schema.
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from aguayluz.models import validate_against_schema  # noqa: PLC0415

    asset = json.loads((outputs / "utility_assets.json").read_text())[0]
    validate_against_schema("utility_asset", asset)
    assert asset["vpuid"] == "21"
    assert asset["attribute_coverage"] == "partial"

    validate_against_schema(
        "source_manifest", json.loads((outputs / "source_manifest.json").read_text())
    )
    validate_against_schema(
        "review_queue", json.loads((outputs / "review_queue.json").read_text())
    )
    validate_against_schema(
        "integration_report", json.loads((outputs / "integration_report.json").read_text())
    )
    validate_against_schema(
        "base44_export", json.loads((outputs / "base44_export.json").read_text())
    )


# ---------- live mode ----------


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("EPA_WATERS_API_KEY") and not os.environ.get("API_DATA_GOV_KEY"),
    reason="live smoke requires EPA_WATERS_API_KEY or API_DATA_GOV_KEY",
)
def test_smoke_live_mode_succeeds(tmp_path):
    outputs = tmp_path / "outputs_live"
    proc = _run_smoke(outputs, demo_mode=False)
    assert proc.returncode == 0, proc.stderr
    line = proc.stdout.strip().splitlines()[-1]
    assert line.startswith("COMID=")
    # Live response should still be VPU 21 for Lago La Plata.
    assert "VPU=21" in line
    assert "attribute_coverage=partial" in line
