#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from aguayluz.usace_corpus import (
    DiscoveryCandidate,
    discover_saj_environmental_documents,
    utc_now,
)
from aguayluz.usace_corpus_adapters import discover_generic_index, discover_pr_scoped_index
from aguayluz.usace_enterprise_adapters import fetch_dspace7_all, pal_search_capability_receipt
from aguayluz.usace_manifestation import download_manifestation

REQUIRED_ROLES = {
    "PRIMARY_REPORT_SOURCE",
    "CURRENT_REGULATORY_SOURCE",
    "HISTORICAL_BACKFILL_SOURCE",
    "PROJECT_DISCOVERY_SOURCE",
}


def _load_v2_module():
    path = Path(__file__).resolve().with_name("harvest_usace_pr_v2.py")
    spec = importlib.util.spec_from_file_location("harvest_usace_pr_v2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load v2 ContentDM pagination module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ValueError("registry sources must be a non-empty list")
    ids = [row.get("source_id") for row in rows]
    if None in ids or len(ids) != len(set(ids)):
        raise ValueError("source_id must be present and unique")
    declared = payload.get("certification_invariants", {}).get("declared_source_count")
    if declared is not None and int(declared) != len(rows):
        raise ValueError("declared_source_count does not match registry rows")
    return payload


def execution_class(source: dict[str, Any]) -> str:
    role = str(source.get("role") or "UNDECLARED")
    state = str(source.get("adapter_state") or "UNDECLARED")
    if role == "SECONDARY_REFERENCE_SOURCE" or state.startswith(("REFERENCE_ONLY", "SECONDARY_")):
        return "REFERENCE_OR_CROSSCHECK"
    if state.startswith("BLOCKED_"):
        return "BLOCKED"
    if source.get("adapter"):
        return "EXECUTE"
    return "BLOCKED"


def execute_source(client: httpx.Client, source: dict[str, Any], *, v2: Any):
    receipt: dict[str, Any] = {
        "source_id": source["source_id"],
        "role": source.get("role"),
        "url": source["url"],
        "adapter": source.get("adapter"),
        "adapter_state_declared": source.get("adapter_state"),
        "started_utc": utc_now(),
        "candidate_count": 0,
        "state": "OPEN",
    }
    kind = execution_class(source)
    receipt["execution_class"] = kind
    if kind == "REFERENCE_OR_CROSSCHECK":
        receipt["state"] = "PASS_DECLARED_REFERENCE_OR_CROSSCHECK"
        return [], receipt
    if kind == "BLOCKED":
        if source.get("adapter") == "pal_api":
            receipt["capability"] = pal_search_capability_receipt(source)
        receipt["state"] = str(source.get("adapter_state") or "BLOCKED_NO_ADAPTER")
        return [], receipt

    adapter = str(source["adapter"])
    try:
        if adapter == "contentdm_api":
            found, pagination = v2.fetch_contentdm_all(client, source)
            receipt["pagination"] = pagination
            receipt["state"] = (
                "PASS_DISCOVERY"
                if pagination["pagination_state"] == "PASS"
                else "UNRESOLVED_PAGINATION"
            )
        elif adapter == "dspace7_api":
            found, pagination = fetch_dspace7_all(client, source)
            receipt["pagination"] = asdict(pagination)
            receipt["state"] = (
                "PASS_DISCOVERY" if pagination.state == "PASS" else pagination.state
            )
        else:
            response = client.get(source["url"])
            response.raise_for_status()
            receipt["http_status"] = response.status_code
            receipt["content_type"] = response.headers.get("content-type")
            if adapter == "saj_environmental_documents":
                found = discover_saj_environmental_documents(
                    response.text,
                    source_id=source["source_id"],
                    source_page=source["url"],
                )
                receipt["state"] = "PASS_DISCOVERY"
            elif adapter == "pr_scoped_index":
                found = discover_pr_scoped_index(
                    response.text,
                    source_id=source["source_id"],
                    source_page=source["url"],
                    require_document_like=bool(source.get("require_document_like", False)),
                )
                receipt["state"] = "UNRESOLVED_OVERDISCOVERY_REQUIRES_CLASSIFICATION"
            elif adapter == "generic_mixed_index":
                regex = source.get("include_href_regex")
                if not regex:
                    raise ValueError("generic_mixed_index requires include_href_regex")
                found = discover_generic_index(
                    response.text,
                    source_id=source["source_id"],
                    source_page=source["url"],
                    include_href_regex=str(regex),
                )
                receipt["state"] = "UNRESOLVED_CHILD_PR_CLASSIFICATION_REQUIRED"
            else:
                found = []
                receipt["state"] = "BLOCKED_ADAPTER_NOT_IMPLEMENTED"
        receipt["candidate_count"] = len(found)
        return found, receipt
    except Exception as exc:
        receipt["state"] = "UNAVAILABLE_RUNTIME_OR_SOURCE"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        return [], receipt


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="USACE Puerto Rico hydospatial harvester v4")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download-direct", action="store_true")
    args = parser.parse_args()

    registry = load_registry(args.registry)
    args.output.mkdir(parents=True, exist_ok=True)
    v2 = _load_v2_module()
    candidates: list[DiscoveryCandidate] = []
    source_receipts: list[dict[str, Any]] = []
    headers = {"User-Agent": "aguayluz-pr-usace-harvester/4.0 (+public research corpus)"}

    with httpx.Client(
        timeout=httpx.Timeout(60, connect=20), headers=headers, follow_redirects=True
    ) as client:
        for source in registry["sources"]:
            found, receipt = execute_source(client, source, v2=v2)
            candidates.extend(found)
            source_receipts.append(receipt)

        write_csv(args.output / "candidates.csv", [asdict(row) for row in candidates])

        retrievals: list[dict[str, Any]] = []
        if args.download_direct:
            for candidate in candidates:
                clean = candidate.url_canonical.lower().split("?", 1)[0]
                direct = clean.endswith(
                    (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".kmz", ".kml")
                )
                if not direct:
                    retrievals.append(
                        {
                            "source_id": candidate.source_id,
                            "url": candidate.url_canonical,
                            "state": "UNRESOLVED_FAMILY_OR_DETAIL_PAGE_EXPANSION_REQUIRED",
                        }
                    )
                    continue
                try:
                    receipt = download_manifestation(
                        client,
                        candidate.url_canonical,
                        source_id=candidate.source_id,
                        output_dir=args.output / "raw",
                    )
                    retrievals.append({**asdict(receipt), "state": "RETRIEVED"})
                except Exception as exc:
                    retrievals.append(
                        {
                            "source_id": candidate.source_id,
                            "url": candidate.url_canonical,
                            "state": "UNAVAILABLE_RUNTIME_OR_SOURCE",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            (args.output / "retrieval_receipts.json").write_text(
                json.dumps(retrievals, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    required = [row for row in source_receipts if row.get("role") in REQUIRED_ROLES]
    blocking = [row for row in required if not str(row.get("state", "")).startswith("PASS_")]
    snapshot = {
        "snapshot_version": "4.0.0",
        "created_utc": utc_now(),
        "registry_version": registry.get("registry_version"),
        "declared_source_count": len(source_receipts),
        "required_source_count": len(required),
        "candidate_count": len(candidates),
        "source_receipts": source_receipts,
        "blocking_required_source_count": len(blocking),
        "blocking_required_source_ids": [row["source_id"] for row in blocking],
        "source_arithmetic": {
            "declared": len(source_receipts),
            "required": len(required),
            "reference_or_crosscheck": sum(
                1 for row in source_receipts if row.get("execution_class") == "REFERENCE_OR_CROSSCHECK"
            ),
            "blocking_required": len(blocking),
        },
        "certification_state": (
            "OPEN_SOURCE_BLOCKERS"
            if blocking
            else "OPEN_MANIFESTATION_FAMILY_AND_IDENTITY_ADJUDICATION"
        ),
        "certified": False,
    }
    (args.output / "discovery_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
