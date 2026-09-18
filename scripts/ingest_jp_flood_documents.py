#!/usr/bin/env python3
"""Consume Spiderweb's JP flood-document manifest into AguaYLuz."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_TOTAL = 78
EXPECTED_AVAILABLE = 76
EXPECTED_LISTED_BUT_MISSING = 1
EXPECTED_NOT_LISTED = 1
SOURCE_STATES = {"AVAILABLE", "LISTED_BUT_MISSING", "NOT_LISTED"}


def validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    docs = manifest.get("documents")
    if not isinstance(docs, list):
        raise ValueError("manifest.documents must be a list")
    if len(docs) != EXPECTED_TOTAL:
        raise ValueError(f"expected {EXPECTED_TOTAL} municipality bindings, got {len(docs)}")
    names = [d.get("municipality") for d in docs]
    if any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError("every document must have a canonical municipality")
    if len(set(names)) != EXPECTED_TOTAL:
        raise ValueError("municipality bindings must be unique")
    if any(d.get("source_state") not in SOURCE_STATES for d in docs):
        raise ValueError("invalid source_state")
    if sum(d["source_state"] == "AVAILABLE" for d in docs) != EXPECTED_AVAILABLE:
        raise ValueError("AVAILABLE count mismatch")
    if sum(d["source_state"] == "LISTED_BUT_MISSING" for d in docs) != EXPECTED_LISTED_BUT_MISSING:
        raise ValueError("LISTED_BUT_MISSING count mismatch")
    if sum(d["source_state"] == "NOT_LISTED" for d in docs) != EXPECTED_NOT_LISTED:
        raise ValueError("NOT_LISTED count mismatch")
    q = next((d for d in docs if d["municipality"] == "Quebradillas"), None)
    f = next((d for d in docs if d["municipality"] == "Florida"), None)
    if not q or q["source_state"] != "LISTED_BUT_MISSING":
        raise ValueError("Quebradillas must remain LISTED_BUT_MISSING")
    if not f or f["source_state"] != "NOT_LISTED":
        raise ValueError("Florida must remain NOT_LISTED")
    for d in (q, f):
        if d.get("fallback_document_class") != "hazard_mitigation_plan" or not d.get("fallback_url"):
            raise ValueError(f'{d["municipality"]} requires authoritative HMP fallback')
        if d.get("fallback_relationship") != "authoritative_fallback_not_equivalent":
            raise ValueError("fallback must remain explicitly non-equivalent")
    return docs


def build_lookup(manifest: dict[str, Any]) -> dict[str, Any]:
    docs = validate_manifest(manifest)
    lookup = {}
    for d in docs:
        use_fallback = d["source_state"] != "AVAILABLE"
        op = d.get("operational_document") or {}
        lookup[d["municipality"]] = {
            "municipality": d["municipality"],
            "source_state": d["source_state"],
            "series_document_class": d.get("document_class"),
            "series_source_url": d.get("source_url"),
            "equivalent_series_member": d.get("equivalent_series_member"),
            "operational_document_class": (
                d.get("fallback_document_class") if use_fallback else d.get("document_class")
            ),
            "operational_source_url": d.get("fallback_url") if use_fallback else d.get("source_url"),
            "fallback_relationship": d.get("fallback_relationship"),
            "filename": op.get("filename"),
            "local_path": op.get("local_path"),
            "sha256": op.get("sha256"),
            "byte_size": op.get("byte_size"),
            "acquisition_status": op.get("acquisition_status"),
        }
    return {
        "schema_version": "1.1",
        "source_manifest_version": manifest.get("manifest_version"),
        "source_authority": manifest.get("authority"),
        "source_portal_url": manifest.get("portal_url"),
        "source_state_enum": sorted(SOURCE_STATES),
        "counts": {
            "municipalities": 78,
            "available_flood_maps": 76,
            "listed_but_missing": 1,
            "not_listed": 1,
            "authoritative_fallbacks": 2,
            "operational_coverage": 78,
        },
        "by_municipality": lookup,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", default="data/jp_flood_documents.json")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out = build_lookup(manifest)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "JP_FLOOD_DOCUMENT_CONSUMER_GATE = PASS "
        "(76 AVAILABLE + 1 LISTED_BUT_MISSING + 1 NOT_LISTED = 78)"
    )


if __name__ == "__main__":
    main()
