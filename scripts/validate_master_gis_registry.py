"""Fail-closed validation for the AguaYLuz master GIS layer registry.

This checks the planning registry's internal integrity, not source completeness
or release certification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_ATOMIC_FIELDS = {
    "layer_id", "group_id", "source_authority", "source_url",
    "source_record_id", "manifestation_sha256", "geometry_type", "crs",
    "coverage_scope", "valid_from", "valid_to", "retrieved_at_utc",
    "evidence_class", "refresh_policy", "render_style",
    "interaction_contract", "certification_state",
}
EVIDENCE_PLANES = {"OBSERVED", "COMPUTED", "HYPOTHETICAL", "UNRESOLVED"}


def validate_registry(document: dict) -> list[str]:
    errors: list[str] = []
    if document.get("schema_version") != "1.0.0":
        errors.append("unexpected schema_version")
    if document.get("completeness_claimed") is not False:
        errors.append("completeness_claimed must be false until independent certification")
    if document.get("certification_state") != "OPEN":
        errors.append("registry certification cannot be inferred from this validator")
    if set(document.get("evidence_planes", [])) != EVIDENCE_PLANES:
        errors.append("evidence planes must include all four distinct states")
    scope = document.get("scope") or {}
    if set(scope.get("land", [])) != {"Puerto Rico main island", "Vieques", "Culebra"}:
        errors.append("missing or unexpected land coverage scope")
    if not scope.get("marine"):
        errors.append("marine scope is required")
    groups = document.get("groups")
    if not isinstance(groups, list) or not groups:
        errors.append("groups must be a nonempty array")
        groups = []
    ids = [g.get("group_id") for g in groups if isinstance(g, dict)]
    if len(ids) != len(groups) or len(set(ids)) != len(ids) or any(not x for x in ids):
        errors.append("group identifiers must be nonempty and unique")
    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = group.get("group_id")
        if not group.get("planned_sublayers"):
            errors.append(f"{gid}: planned_sublayers empty")
        if group.get("implementation_state") == "CERTIFIED":
            errors.append(f"{gid}: cannot claim certified implementation")
    missing = REQUIRED_ATOMIC_FIELDS - set(document.get("required_atomic_layer_fields", []))
    if missing:
        errors.append("missing required atomic fields: " + ", ".join(sorted(missing)))
    if not document.get("release_gates"):
        errors.append("release gates missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("config/master_gis_layer_registry.v1.json"))
    args = parser.parse_args()
    try:
        doc = json.loads(args.registry.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FAIL: unable to read registry: {exc}")
        return 2
    errors = validate_registry(doc)
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print(f"PASS: registry structure validated ({len(doc['groups'])} groups); release remains BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
