"""Validate preliminary GIS source candidate catalog; never certify source coverage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def validate_catalog(catalog: dict, registry: dict) -> list[str]:
    errors = []
    if catalog.get("schema_version") != "1.0.0":
        errors.append("unsupported catalog schema")
    if catalog.get("completeness_claimed") is not False:
        errors.append("unverified catalog cannot claim completeness")
    if catalog.get("state") != "CANDIDATES_UNVERIFIED":
        errors.append("catalog state must remain CANDIDATES_UNVERIFIED")
    records = catalog.get("records")
    if not isinstance(records, list):
        return errors + ["records must be a list"]
    ids = [r.get("candidate_id") for r in records if isinstance(r, dict)]
    if len(ids) != len(records) or len(set(ids)) != len(ids):
        errors.append("duplicate or malformed candidate IDs")
    group_ids = {g["group_id"] for g in registry.get("groups", [])}
    for record in records:
        if not isinstance(record, dict):
            continue
        ident = record.get("candidate_id", "<unknown>")
        if record.get("group_id") not in group_ids:
            errors.append(f"{ident}: unknown group")
        url = record.get("directory_url", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(f"{ident}: invalid source directory URL")
        if record.get("discovery_state") != "NOT_VERIFIED":
            errors.append(f"{ident}: discovery status requires independent evidence")
        for field in ("record_count", "retained_count", "excluded_count", "unresolved_count"):
            value = record.get(field)
            if value is not None and (type(value) is not int or value < 0):
                errors.append(f"{ident}: invalid {field}")
        count = record.get("record_count")
        parts = [record.get(k) for k in ("retained_count", "excluded_count", "unresolved_count")]
        if count is not None and all(v is not None and type(v) is int and v >= 0 for v in parts):
            if sum(parts) != count:
                errors.append(f"{ident}: count closure failure")
        elif count is not None or any(v is not None for v in parts):
            errors.append(f"{ident}: partial source arithmetic")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("config/gis_source_candidates.v1.json"))
    parser.add_argument("--registry", type=Path, default=Path("config/master_gis_layer_registry.v1.json"))
    args = parser.parse_args()
    try:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        registry = json.loads(args.registry.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 2
    errors = validate_catalog(catalog, registry)
    for error in errors:
        print("FAIL:", error)
    if errors:
        return 1
    print(f"PASS: {len(catalog['records'])} candidate records structurally valid; discovery and release NOT CERTIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
