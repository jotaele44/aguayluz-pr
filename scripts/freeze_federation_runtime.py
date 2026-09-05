#!/usr/bin/env python3
"""Freeze one coherent AguaYLuz federation runtime manifestation.

The receipt binds every emitted byte to one Git commit/tree, closes the core
operator-output arithmetic, re-verifies the canonical stream manifest, and
records whether the same commit is spatial-certification eligible. Evidence-only
mode may freeze a BLOCKED package for downstream audit without promoting it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
FEDERATION = OUTPUTS / "federation"
REQUIRED_OPERATOR = {
    "utility_assets.json",
    "service_events.json",
    "monitoring_readings.json",
    "source_manifest.json",
    "review_queue.json",
    "bridge_summary.json",
    "hub_export.json",
    "integration_report.json",
}
REQUIRED_STREAMS = {"sources", "entities", "relationships", "alerts"}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_repo_validator():
    path = ROOT / "scripts" / "validate_repo.py"
    spec = importlib.util.spec_from_file_location("aguayluz_validate_repo_freeze", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/validate_repo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def freeze(test_receipt: Path, *, evidence_only: bool) -> dict[str, Any]:
    problems: list[str] = []
    commit_sha = _git("rev-parse", "HEAD")
    tree_sha = _git("rev-parse", "HEAD^{tree}")

    missing_operator = sorted(name for name in REQUIRED_OPERATOR if not (OUTPUTS / name).is_file())
    if missing_operator:
        problems.append(f"missing operator outputs: {missing_operator}")
    if not (FEDERATION / "manifest.json").is_file():
        problems.append("missing canonical federation manifest")
    if problems:
        return {
            "ok": False,
            "certification_eligible": False,
            "producer_commit": commit_sha,
            "producer_tree": tree_sha,
            "problems": problems,
        }

    receipt_gate = _load_repo_validator()._validate_test_receipt(test_receipt)
    if receipt_gate["status"] != "PASS":
        problems.append(str(receipt_gate["details"]))

    assets = _json(OUTPUTS / "utility_assets.json")
    events = _json(OUTPUTS / "service_events.json")
    source_manifest = _json(OUTPUTS / "source_manifest.json")
    review_queue = _json(OUTPUTS / "review_queue.json")
    hub_export = _json(OUTPUTS / "hub_export.json")
    integration = _json(OUTPUTS / "integration_report.json")
    if not isinstance(assets, list) or not isinstance(events, list):
        problems.append("utility_assets/service_events must be arrays")
        assets = [] if not isinstance(assets, list) else assets
        events = [] if not isinstance(events, list) else events

    records_total = len(assets) + len(events)
    coverage = integration.get("coverage", {}) if isinstance(integration, dict) else {}
    expected = coverage.get("expected")
    located = coverage.get("located")
    ingested = coverage.get("ingested")
    unresolved = coverage.get("unresolved")
    if expected != records_total:
        problems.append(f"coverage expected={expected} != assets+events={records_total}")
    if ingested != expected:
        problems.append(f"coverage ingested={ingested} != expected={expected}")
    if isinstance(expected, int) and isinstance(located, int) and unresolved != expected - located:
        problems.append(f"coverage unresolved={unresolved} != expected-located={expected - located}")
    if isinstance(expected, int) and isinstance(located, int):
        computed_pct = 0.0 if expected <= 0 else round((located / expected) * 100, 2)
        if coverage.get("coverage_pct") != computed_pct:
            problems.append(
                f"coverage_pct={coverage.get('coverage_pct')} != computed={computed_pct}"
            )
    if hub_export.get("records_total") != records_total:
        problems.append("hub_export records_total does not close to assets+events")
    if hub_export.get("coverage_pct") != coverage.get("coverage_pct"):
        problems.append("hub_export/integration coverage_pct mismatch")
    if hub_export.get("status") != "PASS":
        problems.append(f"finalized hub_export status is {hub_export.get('status')!r}, expected PASS")

    gate_rows = integration.get("gates", []) if isinstance(integration, dict) else []
    gate_ids = [row.get("id") for row in gate_rows if isinstance(row, dict)]
    if len(gate_ids) != len(set(gate_ids)):
        problems.append("integration gate ids are duplicated")
    expected_gate_ids = {f"G0{i}_" for i in range(1, 9)}
    observed_prefixes = {str(gate_id)[:4] for gate_id in gate_ids if isinstance(gate_id, str)}
    if observed_prefixes != expected_gate_ids:
        problems.append(
            f"integration gate set does not close: observed={sorted(observed_prefixes)}"
        )
    nonpass_gates = [
        f"{row.get('id')}={row.get('status')}"
        for row in gate_rows
        if isinstance(row, dict) and row.get("status") != "PASS"
    ]
    if nonpass_gates:
        problems.append(f"non-PASS finalized integration gates: {nonpass_gates}")

    entries = source_manifest.get("entries", []) if isinstance(source_manifest, dict) else []
    refs = [entry.get("source_ref") for entry in entries if isinstance(entry, dict)]
    if len(refs) != len(set(refs)):
        problems.append("source_manifest contains duplicate source_ref values")
    review_items = review_queue.get("items", []) if isinstance(review_queue, dict) else []
    if not isinstance(review_items, list):
        problems.append("review_queue items must be an array")
        review_items = []

    canonical = _json(FEDERATION / "manifest.json")
    manifest_files = canonical.get("files", []) if isinstance(canonical, dict) else []
    seen_streams: set[str] = set()
    canonical_counts: dict[str, int] = {}
    for entry in manifest_files:
        if not isinstance(entry, dict):
            problems.append("canonical manifest file entry must be an object")
            continue
        filename = entry.get("filename")
        stream = entry.get("stream")
        if not isinstance(filename, str) or not isinstance(stream, str):
            problems.append("canonical manifest file entry missing filename/stream")
            continue
        path = FEDERATION / filename
        if not path.is_file():
            problems.append(f"canonical stream missing: {filename}")
            continue
        if stream in seen_streams:
            problems.append(f"duplicate canonical stream: {stream}")
        seen_streams.add(stream)
        actual_hash = _sha256(path)
        actual_count = _line_count(path)
        if entry.get("sha256") != actual_hash:
            problems.append(f"canonical stream hash mismatch: {filename}")
        if entry.get("record_count") != actual_count:
            problems.append(f"canonical stream count mismatch: {filename}")
        canonical_counts[stream] = actual_count
    if seen_streams != REQUIRED_STREAMS:
        problems.append(f"canonical stream set mismatch: {sorted(seen_streams)}")

    all_files: list[dict[str, Any]] = []
    for path in sorted(p for p in OUTPUTS.rglob("*") if p.is_file()):
        if path.is_symlink():
            problems.append(f"symlink not allowed in runtime manifestation: {path.relative_to(ROOT)}")
            continue
        rel = path.relative_to(ROOT).as_posix()
        all_files.append({"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path)})

    spatial_proc = subprocess.run(
        [str(ROOT / "scripts" / "validate_federation_spatial.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        spatial_payload = json.loads(spatial_proc.stdout)
    except json.JSONDecodeError:
        spatial_payload = {
            "ok": False,
            "certification_state": "UNRESOLVED",
            "raw": spatial_proc.stdout[-1000:],
        }
    spatial_pass = spatial_proc.returncode == 0 and spatial_payload.get("certification_ready") is True
    if not spatial_pass and not evidence_only:
        problems.append("producer spatial certification gate set is not fully PASS")

    certification_eligible = not problems and spatial_pass
    result = {
        "schema_version": "aguayluz_federation_runtime_freeze_v1",
        "repository": "jotaele44/aguayluz-pr",
        "producer_commit": commit_sha,
        "producer_tree": tree_sha,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "mode": "EVIDENCE_ONLY" if evidence_only else "CERTIFICATION",
        "test_receipt": receipt_gate,
        "spatial_certification": spatial_payload,
        "counts": {
            "utility_assets": len(assets),
            "service_events": len(events),
            "records_total": records_total,
            "source_manifest_entries": len(entries),
            "review_queue_items": len(review_items),
            "canonical_streams": canonical_counts,
        },
        "files": all_files,
        "file_count": len(all_files),
        "certification_eligible": certification_eligible,
        "problems": problems,
        "state": "PASS" if certification_eligible else ("AUDIT_ONLY" if evidence_only and not problems else "BLOCKED"),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--evidence-only",
        action="store_true",
        help="freeze a coherent package even while spatial certification gates remain unresolved",
    )
    args = parser.parse_args(argv)
    try:
        result = freeze(args.test_receipt, evidence_only=args.evidence_only)
    except Exception as exc:  # noqa: BLE001 - fail closed
        result = {
            "schema_version": "aguayluz_federation_runtime_freeze_v1",
            "state": "BLOCKED",
            "certification_eligible": False,
            "problems": [f"{type(exc).__name__}: {exc}"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.evidence_only:
        # Evidence-only succeeds only when the runtime package itself is coherent;
        # unresolved spatial certification is expected and recorded, not promoted.
        non_spatial = [p for p in result.get("problems", []) if "spatial certification" not in str(p)]
        return 0 if not non_spatial else 1
    return 0 if result.get("certification_eligible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
