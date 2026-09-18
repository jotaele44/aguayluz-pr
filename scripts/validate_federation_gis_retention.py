#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "governance" / "federation_gis_retention_v1.json"


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _changed_paths(base: str, head: str, expected: list[str]) -> set[str]:
    proc = _git("diff", "--name-only", f"{base}..{head}", "--", *expected)
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def validate_retention(ledger: dict[str, Any]) -> dict[str, Any]:
    problems: list[str] = []
    expected = ledger.get("expected_paths")
    if not isinstance(expected, list) or len(expected) != ledger.get("expected_path_count"):
        return {"ok": False, "problems": ["expected path count does not close"], "expected": 0}
    if len(expected) != len(set(expected)):
        problems.append("expected_paths contains duplicates")

    missing = [path for path in expected if not (ROOT / path).is_file()]
    if missing:
        problems.append(f"missing GIS paths: {missing}")

    source_merge = str(ledger.get("source_merge_commit", ""))
    pre_repair = str(ledger.get("pre_repair_snapshot_commit", ""))
    head = _git("rev-parse", "HEAD").stdout.strip()

    for label, ancestor in (("source_merge_commit", source_merge), ("pre_repair_snapshot_commit", pre_repair)):
        proc = _git("merge-base", "--is-ancestor", ancestor, head, check=False)
        if proc.returncode != 0:
            problems.append(f"{label} is not an ancestor of current HEAD")

    source_changed = _changed_paths(source_merge, head, expected)
    allowed_source_changed = set(ledger.get("allowed_post_merge_modified_paths", []))
    unexpected_source_changes = sorted(source_changed - allowed_source_changed)
    if unexpected_source_changes:
        problems.append(f"unadjudicated post-merge GIS changes: {unexpected_source_changes}")

    repair_changed = _changed_paths(pre_repair, head, expected)
    expected_repair_changed = set(ledger.get("repair_modified_paths", []))
    if repair_changed != expected_repair_changed:
        problems.append(
            "repair GIS delta mismatch: "
            f"observed={sorted(repair_changed)} expected={sorted(expected_repair_changed)}"
        )

    marker_failures: list[str] = []
    markers = ledger.get("semantic_markers", {})
    if not isinstance(markers, dict):
        markers = {}
        problems.append("semantic_markers must be an object")
    for rel in sorted(source_changed):
        required = markers.get(rel)
        if not isinstance(required, list) or not required:
            marker_failures.append(f"{rel}: no semantic markers declared")
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        missing_markers = [marker for marker in required if marker not in text]
        if missing_markers:
            marker_failures.append(f"{rel}: missing markers {missing_markers}")
    if marker_failures:
        problems.extend(marker_failures)

    return {
        "ok": not problems,
        "head": head,
        "expected": len(expected),
        "present": len(expected) - len(missing),
        "missing": missing,
        "source_merge_changed_paths": sorted(source_changed),
        "repair_changed_paths": sorted(repair_changed),
        "problems": problems,
        "classification": (
            "RETAINED_20_OF_20_WITH_ADJUDICATED_POST_MERGE_CHANGES"
            if not problems
            else "RETENTION_UNRESOLVED"
        ),
    }


def main() -> int:
    try:
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "problems": [f"cannot read retention ledger: {exc}"]}, indent=2))
        return 1
    result = validate_retention(ledger)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
