#!/usr/bin/env python3
"""Project canonical infrastructure objects into a read-only legacy compatibility view.

This tool never writes to data/utility_assets.jsonl and never establishes identity.
It emits a legacy record only when every field required by utility_asset.schema.json
can be supplied explicitly. Otherwise it returns a blocked projection receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _index_terms(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {term["term_id"]: term for term in registry["terms"]}


def _index_rules(rules: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {rule["canonical_term_id"]: rule for rule in rules["rules"]}


def _projection_id(object_id: str, canonical_term_id: str, rules_version: str) -> str:
    digest = hashlib.sha256(
        f"{object_id}|{canonical_term_id}|{rules_version}".encode()
    ).hexdigest()[:16].upper()
    return f"AYL_COMPAT_{digest}"


def project_object(
    obj: dict[str, Any],
    registry: dict[str, Any],
    rules: dict[str, Any],
    legacy_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    term_id = obj.get("canonical_term_id")
    if term_id is None:
        raise ValueError("canonically untyped objects cannot be projected")

    terms = _index_terms(registry)
    if term_id not in terms:
        raise ValueError(f"unknown canonical term: {term_id}")
    term = terms[term_id]
    rules_version = rules["schema_version"]

    explicit = _index_rules(rules).get(term_id)
    if explicit:
        legacy_type = explicit["legacy_asset_type"]
        legacy_subtype = explicit["legacy_asset_subtype"]
    else:
        domain = term["domain"]
        legacy_type = rules["domain_to_legacy_asset_type"].get(domain, "unknown")
        legacy_subtype = None

    context = legacy_context or {}
    required_context = (
        "municipality",
        "geometry_type",
        "status",
        "source_ref",
        "evidence_tier",
        "confidence",
        "review_status",
    )
    missing = [key for key in required_context if context.get(key) is None]
    if not obj.get("public_label"):
        missing.append("asset_name")
    if legacy_subtype is None:
        missing.append("asset_subtype")

    projection_state = "READY"
    if legacy_subtype is None:
        projection_state = "BLOCKED_UNMAPPED_SUBTYPE"
    elif missing:
        projection_state = "BLOCKED_MISSING_CONTEXT"

    legacy_record = None
    if projection_state == "READY":
        legacy_record = {
            "asset_id": obj["object_id"],
            "asset_name": obj["public_label"],
            "asset_type": legacy_type,
            "asset_subtype": legacy_subtype,
            "operator": context.get("operator"),
            "municipality": context["municipality"],
            "lat": context.get("lat"),
            "lon": context.get("lon"),
            "geometry_type": context["geometry_type"],
            "status": context["status"],
            "source_ref": context["source_ref"],
            "source_hash": context.get("source_hash"),
            "evidence_tier": context["evidence_tier"],
            "confidence": context["confidence"],
            "review_status": context["review_status"],
        }

    return {
        "projection_id": _projection_id(obj["object_id"], term_id, rules_version),
        "object_id": obj["object_id"],
        "canonical_term_id": term_id,
        "rules_version": rules_version,
        "projection_state": projection_state,
        "missing_required_fields": sorted(set(missing)),
        "legacy_record": legacy_record,
        "compatibility_only": True,
        "source_of_truth": "canonical_infrastructure_model",
        "identity_effect": "none",
        "certification_state": (
            "NONCANONICAL"
            if obj.get("identity_state") == "noncanonical_fixture"
            else "PROVISIONAL"
        ),
        "notes": "Derived compatibility receipt; never write back to the production legacy ledger.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--legacy-context", type=Path)
    args = parser.parse_args()

    context = load_json(args.legacy_context) if args.legacy_context else None
    projected = project_object(
        load_json(args.object),
        load_json(args.registry),
        load_json(args.rules),
        context,
    )
    print(json.dumps(projected, ensure_ascii=False, sort_keys=True))
    return 0 if projected["projection_state"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
