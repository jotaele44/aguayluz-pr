#!/usr/bin/env python3
"""Apply a source-aware classification overlay to the frozen v0.1 ontology audit.

The base ontology remains immutable. This tool appends only exact source-supported
legacy pair mappings whose canonical targets already exist in the base registry.
It never changes ``data/utility_assets.jsonl`` and never treats classification as
physical identity.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
BASE_TOOL = Path(__file__).with_name("audit_infrastructure_vocabulary.py")
DEFAULT_ASSETS = REPO / "data" / "utility_assets.jsonl"
DEFAULT_REGISTRY = REPO / "ontology" / "infrastructure_terms.v0.1.json"
DEFAULT_OVERLAY = REPO / "ontology" / "source_aware_crosswalk.v0.1.json"
DEFAULT_REPORT = REPO / "reports" / "infrastructure_source_aware_audit.json"
DEFAULT_DECISIONS = REPO / "reports" / "infrastructure_source_aware_decisions.jsonl"


def _load_base_tool():
    spec = importlib.util.spec_from_file_location("audit_infrastructure_vocabulary", BASE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import base audit tool from {BASE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_overlay(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source-aware overlay must be a JSON object")
    return payload


def merge_registry(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    if str(overlay.get("base_ontology_version")) != str(base.get("ontology_version")):
        raise ValueError("overlay base_ontology_version does not match registry ontology_version")

    merged = json.loads(json.dumps(base))
    existing = {
        (item.get("legacy_asset_type"), item.get("legacy_asset_subtype"))
        for item in merged.get("legacy_crosswalk") or []
    }
    term_ids = {item.get("term_id") for item in merged.get("terms") or []}

    for mapping in overlay.get("mappings") or []:
        key = (mapping.get("legacy_asset_type"), mapping.get("legacy_asset_subtype"))
        if key in existing:
            raise ValueError(f"source-aware overlay duplicates base crosswalk key: {key!r}")
        target = mapping.get("canonical_term_id")
        if target not in term_ids:
            raise ValueError(f"source-aware overlay target is absent from base registry: {target!r}")
        merged.setdefault("legacy_crosswalk", []).append(
            {
                "legacy_asset_type": key[0],
                "legacy_asset_subtype": key[1],
                "state": mapping.get("state", "provisional"),
                "canonical_term_id": target,
                "reason": mapping.get("evidence_basis"),
            }
        )
        existing.add(key)
    return merged


def validate_expected_counts(rows: list[dict[str, Any]], overlay: dict[str, Any]) -> dict[str, Any]:
    actual: dict[tuple[Any, Any], int] = {}
    for row in rows:
        key = (row.get("asset_type"), row.get("asset_subtype"))
        actual[key] = actual.get(key, 0) + 1

    checks = []
    passed = True
    for mapping in overlay.get("mappings") or []:
        key = (mapping.get("legacy_asset_type"), mapping.get("legacy_asset_subtype"))
        expected = mapping.get("expected_current_rows")
        observed = actual.get(key, 0)
        ok = expected is None or observed == expected
        checks.append(
            {
                "legacy_asset_type": key[0],
                "legacy_asset_subtype": key[1],
                "expected_current_rows": expected,
                "observed_current_rows": observed,
                "pass": ok,
            }
        )
        passed = passed and ok
    return {"pass": passed, "checks": checks}


def build_report(assets: Path, registry_path: Path, overlay_path: Path):
    base_tool = _load_base_tool()
    base = base_tool.load_registry(registry_path)
    overlay = load_overlay(overlay_path)
    rows = base_tool.load_jsonl(assets)

    expected_counts = validate_expected_counts(rows, overlay)
    if not expected_counts["pass"]:
        raise ValueError(f"source-aware overlay count drift detected: {expected_counts}")

    merged = merge_registry(base, overlay)
    registry_validation = base_tool.validate_registry(merged)
    if not registry_validation["pass"]:
        raise ValueError(f"merged ontology failed invariants: {registry_validation}")

    decisions, summary = base_tool.classify_rows(rows, merged)
    classified = sum(
        summary["state_counts"].get(state, 0)
        for state in ("pass", "provisional", "candidate_not_identity")
    )
    unresolved = summary["state_counts"].get("unresolved", 0)
    excluded = summary["state_counts"].get("excluded", 0)
    superseded = summary["state_counts"].get("superseded", 0)
    closed_total = classified + unresolved + excluded + superseded

    report = {
        "audit_schema": "aguayluz.infrastructure-source-aware-audit/v0.1",
        "scope": "Bounded to the supplied legacy utility_assets snapshot and exact source-aware overlay mappings.",
        "assets_path": str(assets),
        "assets_sha256": sha256_file(assets),
        "registry_path": str(registry_path),
        "registry_sha256": sha256_file(registry_path),
        "overlay_path": str(overlay_path),
        "overlay_sha256": sha256_file(overlay_path),
        "ontology_version": base.get("ontology_version"),
        "overlay_version": overlay.get("overlay_version"),
        "registry_validation": registry_validation,
        "overlay_expected_counts": expected_counts,
        "summary": summary,
        "arithmetic": {
            "source_rows": len(rows),
            "classified": classified,
            "unresolved": unresolved,
            "excluded": excluded,
            "superseded": superseded,
            "closed_total": closed_total,
            "pass": closed_total == len(rows),
        },
        "certification_state": "provisional" if unresolved else "pass",
        "classification_is_identity": False,
        "universal_exhaustion_claimed": False,
    }
    if not report["arithmetic"]["pass"]:
        raise AssertionError("source-aware classification arithmetic failed to close")
    return report, decisions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--fail-on-unmapped", action="store_true")
    args = parser.parse_args()

    base_tool = _load_base_tool()
    report, decisions = build_report(args.assets, args.registry, args.overlay)
    base_tool.write_json(args.report, report)
    base_tool.write_jsonl(args.decisions, decisions)

    unresolved = int(report["summary"]["state_counts"].get("unresolved", 0))
    print(
        f"source-aware audit rows={report['summary']['row_count']} "
        f"classified={report['arithmetic']['classified']} unresolved={unresolved} "
        f"pairs={report['summary']['unique_raw_pairs']} arithmetic_pass={report['arithmetic']['pass']}"
    )
    return 2 if args.fail_on_unmapped and unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
