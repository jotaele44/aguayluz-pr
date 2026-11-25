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
import hashlib
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
PRODUCER_CONTRACT_SCHEMA = "jp-flood-producer-contract/1.0"
PRODUCER_CONTRACT_SHA256 = "f665aba3176f9defbdce322b1e480c8db596df666ea130ccb435bf46a66a2e78"
PRODUCER_MERGE_SHA = "d6326c04e8ecc585b4068f8252a903246498dbb3"
DEFAULT_PRODUCER_CONTRACT = Path("data/jp_flood_documents_producer_contract.json")
BYTE_CERTIFICATION_SCHEMA = "spiderweb.jp-flood-byte-certification/v1"
BYTE_CERTIFICATION_SHA256 = "e6832834f875900dda4c3f5f3b25444e39e9f804d1279ffb45ddecee9082c60c"
BYTE_CERTIFICATION_SOURCE_MAIN_SHA = "edf35847cd3e031ed9be4b733083e4b7c0c18dbf"
BYTE_CERTIFIED_PRODUCER_SHA = "d6326c04e8ecc585b4068f8252a903246498dbb3"
BYTE_CERTIFIED_CONSUMER_SHA = "324b7057cc8466db061443e1e008bf3f39bb83b3"
BYTE_CERTIFIED_TOTAL_BYTES = 914_381_842
DEFAULT_BYTE_CERTIFICATION = Path("data/jp_flood_documents_byte_certification.json")


def validate_producer_contract(path: Path) -> dict[str, Any]:
    """Validate the immutable Spiderweb producer-contract manifestation by bytes and semantics."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PRODUCER_CONTRACT_SHA256:
        raise ValueError(
            f"producer contract SHA256 mismatch: expected={PRODUCER_CONTRACT_SHA256} got={digest}"
        )
    contract = json.loads(raw)
    if contract.get("schema_version") != PRODUCER_CONTRACT_SCHEMA:
        raise ValueError("producer contract schema mismatch")
    if contract.get("producer") != "spiderweb-pr":
        raise ValueError("producer contract producer mismatch")
    if contract.get("producer_merge_sha") != PRODUCER_MERGE_SHA:
        raise ValueError("producer merge lineage mismatch")

    source = contract.get("source_contract") or {}
    expected = {
        "manifest_version": "2.1",
        "municipalities": EXPECTED_TOTAL,
        "series_listed": 77,
        "series_available": EXPECTED_AVAILABLE,
        "listed_but_missing": EXPECTED_LISTED_BUT_MISSING,
        "not_listed": EXPECTED_NOT_LISTED,
        "authoritative_fallbacks": 2,
        "operational_coverage": EXPECTED_TOTAL,
    }
    for key, value in expected.items():
        if source.get(key) != value:
            raise ValueError(f"producer source contract {key} mismatch")
    if source["series_available"] + source["listed_but_missing"] + source["not_listed"] != EXPECTED_TOTAL:
        raise ValueError("producer source contract arithmetic mismatch")

    q = contract.get("quebradillas_receipt") or {}
    if q.get("pdf_sha256") != QUEBRADILLAS_FROZEN_SHA256:
        raise ValueError("producer contract Quebradillas SHA256 mismatch")
    if q.get("pdf_byte_size") != QUEBRADILLAS_FROZEN_BYTE_SIZE:
        raise ValueError("producer contract Quebradillas byte-size mismatch")

    rules = contract.get("identity_rules") or {}
    if rules.get("quebradillas_source_state") != "LISTED_BUT_MISSING":
        raise ValueError("producer contract Quebradillas source state mismatch")
    if rules.get("florida_source_state") != "NOT_LISTED":
        raise ValueError("producer contract Florida source state mismatch")
    if rules.get("fallback_is_not_equivalent_series_member") is not True:
        raise ValueError("producer contract fallback identity rule mismatch")
    return contract


def validate_byte_certification(path: Path) -> dict[str, Any]:
    """Validate Spiderweb's immutable 78/78 byte-certification receipt."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != BYTE_CERTIFICATION_SHA256:
        raise ValueError(
            f"byte certification SHA256 mismatch: expected={BYTE_CERTIFICATION_SHA256} got={digest}"
        )
    cert = json.loads(raw)
    if cert.get("schema_version") != BYTE_CERTIFICATION_SCHEMA:
        raise ValueError("byte certification schema mismatch")
    if cert.get("certification_state") != "PASS":
        raise ValueError("byte certification state must be PASS")
    if cert.get("producer_main_sha") != BYTE_CERTIFIED_PRODUCER_SHA:
        raise ValueError("byte certification producer lineage mismatch")
    if cert.get("aguayluz_consumer_main_sha") != BYTE_CERTIFIED_CONSUMER_SHA:
        raise ValueError("byte certification consumer baseline mismatch")

    counts = cert.get("counts") or {}
    expected = {
        "municipality_denominator": EXPECTED_TOTAL,
        "series_listed": 77,
        "available": EXPECTED_AVAILABLE,
        "listed_but_missing": EXPECTED_LISTED_BUT_MISSING,
        "not_listed": EXPECTED_NOT_LISTED,
        "operational_document_count": EXPECTED_TOTAL,
        "byte_verified_count": EXPECTED_TOTAL,
        "failure_count": 0,
        "total_bytes": BYTE_CERTIFIED_TOTAL_BYTES,
    }
    for key, value in expected.items():
        if counts.get(key) != value:
            raise ValueError(f"byte certification {key} mismatch")

    gates = cert.get("gates") or {}
    for key in (
        "municipality_denominator",
        "series_listed",
        "available",
        "listed_but_missing",
        "not_listed",
        "operational_document_count",
        "byte_verified_count",
        "failure_count",
    ):
        if gates.get(key) != expected[key]:
            raise ValueError(f"byte certification gate {key} mismatch")

    if cert.get("sha256sums_sha256") != "118fa90880747177cf0349db19ad21bcc8432110b1032dc4d3e5d420cb7fb305":
        raise ValueError("byte certification SHA256SUMS lineage mismatch")
    return cert

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
    parser.add_argument(
        "--producer-contract",
        type=Path,
        default=DEFAULT_PRODUCER_CONTRACT,
        help="Immutable Spiderweb producer-contract manifestation; exact SHA256 required.",
    )
    parser.add_argument(
        "--byte-certification",
        type=Path,
        default=DEFAULT_BYTE_CERTIFICATION,
        help="Immutable Spiderweb 78/78 byte-certification receipt; exact SHA256 required.",
    )
    parser.add_argument("--out", default="data/jp_flood_documents.json")
    args = parser.parse_args()

    producer_contract = validate_producer_contract(args.producer_contract)
    byte_certification = validate_byte_certification(args.byte_certification)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    lookup = build_lookup(manifest)
    lookup["producer_contract"] = {
        "schema_version": producer_contract["schema_version"],
        "producer": producer_contract["producer"],
        "producer_merge_sha": producer_contract["producer_merge_sha"],
        "sha256": PRODUCER_CONTRACT_SHA256,
    }
    lookup["byte_certification"] = {
        "schema_version": byte_certification["schema_version"],
        "certification_state": byte_certification["certification_state"],
        "source_repository": "jotaele44/spiderweb-pr",
        "source_path": "data/jp_flood_documents/certification/2026-09-21/certification.json",
        "source_main_sha": BYTE_CERTIFICATION_SOURCE_MAIN_SHA,
        "certified_producer_sha": byte_certification["producer_main_sha"],
        "certified_consumer_baseline_sha": byte_certification["aguayluz_consumer_main_sha"],
        "sha256": BYTE_CERTIFICATION_SHA256,
        "counts": byte_certification["counts"],
        "sha256sums_sha256": byte_certification["sha256sums_sha256"],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(lookup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "JP_FLOOD_DOCUMENT_CONSUMER_GATE = PASS "
        "(76 AVAILABLE + 1 LISTED_BUT_MISSING + 1 NOT_LISTED = 78; "
        f"Quebradillas frozen fallback; producer_contract_sha256={PRODUCER_CONTRACT_SHA256}; "
        f"byte_certification_sha256={BYTE_CERTIFICATION_SHA256})"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
