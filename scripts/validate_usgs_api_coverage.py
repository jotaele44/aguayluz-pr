#!/usr/bin/env python3
"""Validate the machine-readable USGS Water API category coverage matrix."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
EXPECTED_IDS = {
    "continuous_values",
    "daily_values",
    "monitoring_locations",
    "time_series_metadata",
    "ogc_apis",
    "water_quality_portal",
    "samples_api",
    "statistics_api",
    "rtfi",
    "nims",
}


def _load_refresh(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("aguayluz_refresh", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_document(document: dict, repo: Path = REPO) -> list[str]:
    errors: list[str] = []
    categories = document.get("categories")
    if not isinstance(categories, list):
        return ["categories must be an array"]
    ids = [str(item.get("id") or "") for item in categories if isinstance(item, dict)]
    missing = EXPECTED_IDS - set(ids)
    extra = set(ids) - EXPECTED_IDS
    if missing:
        errors.append(f"missing categories: {sorted(missing)}")
    if extra:
        errors.append(f"unknown categories: {sorted(extra)}")
    if len(ids) != len(set(ids)):
        errors.append("duplicate category ids")

    refresh = _load_refresh(repo / "scripts" / "refresh.py")
    scheduled: dict[str, set[str]] = {}
    for cadence, plan in refresh.PLANS.items():
        scheduled[cadence] = {str(step[1][0]) for step in plan}

    for item in categories:
        if not isinstance(item, dict):
            errors.append("category entry must be an object")
            continue
        category_id = str(item.get("id") or "<missing>")
        registered = item.get("provider_registered") is True
        monitoring = item.get("observation_monitoring") is True
        producers = item.get("producers")
        artifacts = item.get("artifacts")
        cadences = item.get("cadences")
        status = str(item.get("implementation_status") or "")

        if registered and not monitoring and status not in {"registered_only", "not_implemented"}:
            errors.append(
                f"{category_id}: registered provider cannot claim implementation without monitoring"
            )
        if monitoring:
            if not isinstance(producers, list) or not producers:
                errors.append(f"{category_id}: monitoring requires producer paths")
            else:
                for producer in producers:
                    if not (repo / str(producer)).is_file():
                        errors.append(f"{category_id}: missing producer {producer}")
            if not isinstance(artifacts, list) or not artifacts:
                errors.append(f"{category_id}: monitoring requires output artifacts")
            if not isinstance(cadences, list) or not cadences:
                errors.append(f"{category_id}: monitoring requires scheduled cadence")
            else:
                for cadence in cadences:
                    if cadence not in scheduled:
                        errors.append(f"{category_id}: unknown cadence {cadence}")
                        continue
                    if isinstance(producers, list) and not any(
                        str(producer) in scheduled[cadence] for producer in producers
                    ):
                        errors.append(
                            f"{category_id}: no producer scheduled in cadence {cadence}"
                        )
        if (
            status.startswith("implemented")
            and item.get("live_verified") is True
            and not any(str(path).endswith("_receipt.json") for path in artifacts or [])
        ):
            errors.append(f"{category_id}: live_verified requires a receipt artifact")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("config/usgs_water_api_coverage.json"),
    )
    parser.add_argument("--strict-live", action="store_true")
    args = parser.parse_args()
    document = json.loads(args.matrix.read_text(encoding="utf-8"))
    errors = validate_document(document)
    if args.strict_live:
        for category in document.get("categories", []):
            if category.get("observation_monitoring") and not category.get("live_verified"):
                errors.append(f"{category.get('id')}: live verification pending")
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(f"USGS category coverage: PASS ({len(document['categories'])}/10 categories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
