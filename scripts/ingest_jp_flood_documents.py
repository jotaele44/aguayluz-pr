#!/usr/bin/env python3
"""Consume Spiderweb JP flood-document manifest into AguaYLuz.

Expected source-state contract:
AVAILABLE | LISTED_BUT_MISSING | NOT_LISTED

Current bounded model:
- 76 AVAILABLE flood-zone PDFs
- 1 LISTED_BUT_MISSING series member (Quebradillas)
- 1 NOT_LISTED municipality (Florida)
- Quebradillas operational use is a hash-frozen local HMP manifestation.
- The Quebradillas remote HMP URL is provenance-only, never an operational dependency.
"""
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

QUEBRADILLAS_FROZEN_BYTE_SIZE = 51_199_142
QUEBRADILLAS_FROZEN_SHA256 = (
    "a1a2ccbfe0097da6f531e78f834d01be5a1555700b809d8f68b162db83d23e7a"
)

def validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    docs = manifest.get("documents")
    if not isinstance(docs, list):
        raise ValueError("manifest.documents must be a list")
    if len(docs) != EXPECTED_TOTAL:
        raise ValueError(f"expected {EXPECTED_TOTAL} municipality bindings, got {len(docs)}")

    names = [d.get("municipality") for d in docs]
    if any(not isinstance(name, str) or not name.strip() for name in names):
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
    if not q.get("source_url"):
        raise ValueError("Quebradillas dead series URL must remain preserved")
    if q.get("fallback_operational_mode") != "frozen_local_manifestation":
        raise ValueError("Quebradillas must use frozen_local_manifestation")
    frozen = q.get("frozen_manifestation") or {}
    if frozen.get("sha256") != QUEBRADILLAS_FROZEN_SHA256:
        raise ValueError("Quebradillas frozen SHA256 mismatch")
    if frozen.get("byte_size") != QUEBRADILLAS_FROZEN_BYTE_SIZE:
        raise ValueError("Quebradillas frozen byte-size mismatch")

    operational = q.get("operational_document")
    if operational:
        if operational.get("sha256") != QUEBRADILLAS_FROZEN_SHA256:
            raise ValueError("Quebradillas operational SHA256 mismatch")
        if operational.get("byte_size") != QUEBRADILLAS_FROZEN_BYTE_SIZE:
            raise ValueError("Quebradillas operational byte-size mismatch")

    if not f or f["source_state"] != "NOT_LISTED":
        raise ValueError("Florida must remain NOT_LISTED")
    if f.get("source_url") is not None:
        raise ValueError("Florida must not acquire a fabricated series URL")
    if f.get("fallback_operational_mode") != "remote_fetch":
        raise ValueError("Florida fallback operational mode mismatch")

    for doc in (q, f):
        if doc.get("fallback_document_class") != "hazard_mitigation_plan":
            raise ValueError(f'{doc["municipality"]} requires HMP fallback')
        if not doc.get("fallback_source_url"):
            raise ValueError(f'{doc["municipality"]} fallback provenance/source URL missing')
        if doc.get("fallback_relationship") != "authoritative_fallback_not_equivalent":
            raise ValueError("fallback must remain explicitly non-equivalent")

    return docs

def build_lookup(manifest: dict[str, Any]) -> dict[str, Any]:
    docs = validate_manifest(manifest)
    lookup: dict[str, dict[str, Any]] = {}

    for doc in docs:
        municipality = doc["municipality"]
        use_fallback = doc["source_state"] != "AVAILABLE"
        operational = doc.get("operational_document") or {}
        frozen = doc.get("frozen_manifestation") or {}

        if municipality == "Quebradillas":
            operational_source_url = None
            operational_access_mode = "frozen_local_manifestation"
            expected_sha256 = frozen.get("sha256")
            expected_byte_size = frozen.get("byte_size")
        elif use_fallback:
            operational_source_url = doc.get("fallback_source_url")
            operational_access_mode = doc.get("fallback_operational_mode")
            expected_sha256 = None
            expected_byte_size = None
        else:
            operational_source_url = doc.get("source_url")
            operational_access_mode = "local_cache_or_remote_fetch"
            expected_sha256 = None
            expected_byte_size = None

        lookup[municipality] = {
            "municipality": municipality,
            "source_state": doc["source_state"],
            "series_document_class": doc.get("document_class"),
            "series_source_url": doc.get("source_url"),
            "equivalent_series_member": doc.get("equivalent_series_member"),
            "operational_document_class": (
                doc.get("fallback_document_class") if use_fallback else doc.get("document_class")
            ),
            "operational_access_mode": operational_access_mode,
            "operational_source_url": operational_source_url,
            "provenance_fallback_source_url": doc.get("fallback_source_url"),
            "fallback_source_access_state": doc.get("fallback_source_access_state"),
            "fallback_relationship": doc.get("fallback_relationship"),
            "expected_sha256": expected_sha256,
            "expected_byte_size": expected_byte_size,
            "filename": operational.get("filename") or frozen.get("filename"),
            "local_path": operational.get("local_path"),
            "sha256": operational.get("sha256") or expected_sha256,
            "byte_size": operational.get("byte_size") or expected_byte_size,
            "acquisition_status": operational.get("acquisition_status")
            or ("frozen_manifestation_expected" if municipality == "Quebradillas" else None),
        }

    return {
        "schema_version": "2.1",
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

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", default="data/jp_flood_documents.json")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    lookup = build_lookup(manifest)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(lookup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "JP_FLOOD_DOCUMENT_CONSUMER_GATE = PASS "
        "(76 AVAILABLE + 1 LISTED_BUT_MISSING + 1 NOT_LISTED = 78; "
        "Quebradillas frozen fallback)"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
