#!/usr/bin/env python3
"""Project canonical infrastructure objects into a read-only legacy compatibility view.

This tool never writes to data/utility_assets.jsonl and never establishes identity.
It requires an already-classified canonical object and explicit ontology/rule files.
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


def _projection_id(object_id: str, canonical_term_id: str) -> str:
    digest = hashlib.sha256(f"{object_id}|{canonical_term_id}".encode()).hexdigest()[:16].upper()
    return f"AYL_COMPAT_{digest}"


def project_object(
    obj: dict[str, Any],
    registry: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    term_id = obj.get("canonical_term_id")
    if term_id is None:
        raise ValueError("canonically untyped objects cannot be projected")

    terms = _index_terms(registry)
    if term_id not in terms:
        raise ValueError(f"unknown canonical term: {term_id}")
    term = terms[term_id]

    explicit = _index_rules(rules).get(term_id)
    if explicit:
        legacy_type = explicit["legacy_asset_type"]
        legacy_subtype = explicit["legacy_asset_subtype"]
    else:
        domain = term["domain"]
        legacy_type = rules["domain_to_legacy_asset_type"].get(domain, "unknown")
        legacy_subtype = None

    return {
        "projection_id": _projection_id(obj["object_id"], term_id),
        "object_id": obj["object_id"],
        "legacy_asset_type": legacy_type,
        "legacy_asset_subtype": legacy_subtype,
        "legacy_name": obj.get("public_label"),
        "legacy_operator": None,
        "legacy_lat": None,
        "legacy_lon": None,
        "legacy_status": obj.get("lifecycle_status"),
        "compatibility_only": True,
        "source_of_truth": "canonical_infrastructure_model",
        "identity_effect": "none",
        "certification_state": "NONCANONICAL" if obj.get("identity_state") == "noncanonical_fixture" else "PROVISIONAL",
        "notes": "Derived compatibility view; never write back to the production legacy ledger.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    args = parser.parse_args()

    projected = project_object(load_json(args.object), load_json(args.registry), load_json(args.rules))
    print(json.dumps(projected, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
