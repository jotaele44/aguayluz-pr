#!/usr/bin/env python3
"""Consume Spiderweb's JP flood-document manifest into AguaYLuz.

Input contract:
- exactly 78 municipality bindings
- exactly 77 flood_risk_zone_map rows
- exactly 1 hazard_mitigation_plan row
- Florida is the alternate and is never treated as an equivalent series member

This importer preserves source classification and writes a compact lookup keyed by
canonical municipality name for GUI/offline use.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_TOTAL = 78
EXPECTED_SERIES = 77
EXPECTED_ALTERNATE = 1


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

    series = [d for d in docs if d.get("document_class") == "flood_risk_zone_map"]
    alternate = [d for d in docs if d.get("document_class") == "hazard_mitigation_plan"]

    if len(series) != EXPECTED_SERIES:
        raise ValueError(f"expected {EXPECTED_SERIES} flood-risk maps, got {len(series)}")
    if len(alternate) != EXPECTED_ALTERNATE:
        raise ValueError(f"expected {EXPECTED_ALTERNATE} alternate, got {len(alternate)}")

    florida = [d for d in docs if d.get("municipality") == "Florida"]
    if len(florida) != 1:
        raise ValueError("Florida must resolve to exactly one document")
    f = florida[0]
    if f.get("document_class") != "hazard_mitigation_plan":
        raise ValueError("Florida must remain hazard_mitigation_plan")
    if f.get("equivalent_series_member") is not False:
        raise ValueError("Florida cannot be promoted to an equivalent series member")
    if any(d.get("municipality") == "Florida" for d in series):
        raise ValueError("Florida cannot appear in the 77-map source series")

    return docs


def build_lookup(manifest: dict[str, Any]) -> dict[str, Any]:
    docs = validate_manifest(manifest)
    lookup: dict[str, dict[str, Any]] = {}

    for d in docs:
        municipality = d["municipality"]
        lookup[municipality] = {
            "municipality": municipality,
            "document_class": d.get("document_class"),
            "source_series": d.get("source_series"),
            "equivalent_series_member": d.get("equivalent_series_member"),
            "source_url": d.get("source_url"),
            "final_url": d.get("final_url"),
            "filename": d.get("filename"),
            "local_path": d.get("local_path"),
            "sha256": d.get("sha256"),
            "byte_size": d.get("byte_size"),
            "acquisition_status": d.get("acquisition_status"),
            "relationship_to_series": d.get("relationship_to_series"),
            "series_absence_state": d.get("series_absence_state"),
        }

    return {
        "schema_version": "1.0",
        "source_manifest_version": manifest.get("manifest_version"),
        "source_authority": manifest.get("authority"),
        "source_portal_url": manifest.get("portal_url"),
        "counts": {
            "municipalities": len(lookup),
            "flood_risk_zone_maps": sum(
                x["document_class"] == "flood_risk_zone_map" for x in lookup.values()
            ),
            "authoritative_alternates": sum(
                x["document_class"] == "hazard_mitigation_plan" for x in lookup.values()
            ),
        },
        "by_municipality": lookup,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, help="Spiderweb JP flood-document manifest")
    ap.add_argument("--out", default="data/jp_flood_documents.json")
    args = ap.parse_args()

    src = Path(args.manifest)
    manifest = json.loads(src.read_text(encoding="utf-8"))
    lookup = build_lookup(manifest)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(lookup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    c = lookup["counts"]
    print(
        "JP_FLOOD_DOCUMENT_CONSUMER_GATE = PASS "
        f'({c["flood_risk_zone_maps"]} maps + '
        f'{c["authoritative_alternates"]} alternate = '
        f'{c["municipalities"]} municipalities)'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
