#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from aguayluz.usace_corpus import (
    DiscoveryCandidate,
    discover_contentdm_search,
    discover_saj_environmental_documents,
    download_url,
    utc_now,
)
from aguayluz.usace_corpus_adapters import discover_generic_index, discover_pr_scoped_index


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload.get("sources"), list):
        raise ValueError("registry sources must be a list")
    ids = [row.get("source_id") for row in payload["sources"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source_id in registry")
    return payload


def contentdm_page_url(url: str, page: int) -> str:
    clean = re.sub(r"/page/\d+", "", url)
    marker = re.search(r"/maxRecords/(\d+)", clean)
    if not marker:
        separator = "&" if "?" in clean else "?"
        return f"{clean}{separator}page={page}"
    return clean[: marker.start()] + f"/page/{page}" + clean[marker.start() :]


def contentdm_total(payload: dict[str, Any]) -> int | None:
    value = payload.get("totalResults") or payload.get("total") or payload.get("total_records")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def fetch_contentdm_all(
    client: httpx.Client,
    source: dict[str, Any],
) -> tuple[list[DiscoveryCandidate], dict[str, Any]]:
    candidates: list[DiscoveryCandidate] = []
    page = 1
    seen_item_urls: set[str] = set()
    total_expected: int | None = None
    pages: list[dict[str, Any]] = []
    while True:
        page_url = contentdm_page_url(source["url"], page)
        response = client.get(page_url)
        response.raise_for_status()
        payload = response.json()
        rows = discover_contentdm_search(
            payload,
            source_id=source["source_id"],
            source_page=page_url,
        )
        added = 0
        for row in rows:
            if row.url_canonical in seen_item_urls:
                continue
            seen_item_urls.add(row.url_canonical)
            candidates.append(row)
            added += 1
        if total_expected is None:
            total_expected = contentdm_total(payload)
        items = payload.get("items") or payload.get("results") or []
        pages.append(
            {
                "page": page,
                "url": page_url,
                "http_status": response.status_code,
                "raw_item_count": len(items),
                "new_candidate_count": added,
            }
        )
        if not items:
            break
        if total_expected is not None and len(candidates) >= total_expected:
            break
        if page >= 10_000:
            raise RuntimeError("ContentDM pagination exceeded safety bound")
        page += 1
    receipt = {
        "pagination_state": (
            "PASS" if total_expected is None or len(candidates) >= total_expected else "UNRESOLVED"
        ),
        "total_expected": total_expected,
        "unique_candidate_count": len(candidates),
        "pages": pages,
    }
    return candidates, receipt


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
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
    parser = argparse.ArgumentParser(description="USACE Puerto Rico hydospatial corpus harvester v2")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download-direct", action="store_true")
    args = parser.parse_args()

    registry = load_registry(args.registry)
    args.output.mkdir(parents=True, exist_ok=True)
    source_receipts: list[dict[str, Any]] = []
    all_candidates: list[DiscoveryCandidate] = []

    timeout = httpx.Timeout(60.0, connect=20.0)
    headers = {"User-Agent": "aguayluz-pr-usace-harvester/2.0 (+public research corpus)"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for source in registry["sources"]:
            adapter_state = str(source.get("adapter_state") or "UNDECLARED")
            adapter = source.get("adapter")
            receipt: dict[str, Any] = {
                "source_id": source["source_id"],
                "url": source["url"],
                "adapter": adapter,
                "adapter_state_declared": adapter_state,
                "started_utc": utc_now(),
                "state": "OPEN",
                "candidate_count": 0,
            }
            if adapter_state.startswith("BLOCKED_"):
                receipt["state"] = adapter_state
                source_receipts.append(receipt)
                continue
            if adapter_state.startswith("SECONDARY_REFERENCE_SOURCE"):
                receipt["state"] = "EXCLUDED_FROM_PRIMARY_DISCOVERY_SECONDARY_REFERENCE"
                source_receipts.append(receipt)
                continue
            try:
                if adapter == "contentdm_api":
                    found, pagination = fetch_contentdm_all(client, source)
                    receipt["pagination"] = pagination
                    if pagination["pagination_state"] != "PASS":
                        receipt["state"] = "UNRESOLVED_PAGINATION"
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
                    elif adapter == "pr_scoped_index":
                        found = discover_pr_scoped_index(
                            response.text,
                            source_id=source["source_id"],
                            source_page=source["url"],
                            require_document_like=bool(source.get("require_document_like", False)),
                        )
                    elif adapter == "generic_mixed_index":
                        found = discover_generic_index(
                            response.text,
                            source_id=source["source_id"],
                            source_page=source["url"],
                            include_href_regex=str(source["include_href_regex"]),
                        )
                        receipt["state"] = "UNRESOLVED_CHILD_PR_CLASSIFICATION_REQUIRED"
                    else:
                        found = []
                        receipt["state"] = "BLOCKED_ADAPTER_NOT_IMPLEMENTED"
                all_candidates.extend(found)
                receipt["candidate_count"] = len(found)
                if receipt["state"] == "OPEN":
                    receipt["state"] = "PASS_DISCOVERY"
            except Exception as exc:
                receipt["state"] = "UNAVAILABLE_RUNTIME_OR_SOURCE"
                receipt["error"] = f"{type(exc).__name__}: {exc}"
            source_receipts.append(receipt)

        candidate_rows = [asdict(row) for row in all_candidates]
        _write_csv(args.output / "candidates.csv", candidate_rows)

        if args.download_direct:
            retrieval_rows: list[dict[str, Any]] = []
            for candidate in all_candidates:
                path = candidate.url_canonical.lower().split("?", 1)[0]
                if not path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".kmz", ".kml")):
                    retrieval_rows.append(
                        {
                            "source_id": candidate.source_id,
                            "url": candidate.url_canonical,
                            "state": "UNRESOLVED_FAMILY_OR_DETAIL_PAGE_EXPANSION_REQUIRED",
                        }
                    )
                    continue
                try:
                    retrieval_rows.append(
                        {
                            **asdict(
                                download_url(
                                    client,
                                    candidate.url_canonical,
                                    source_id=candidate.source_id,
                                    output_dir=args.output / "raw",
                                )
                            ),
                            "state": "RETRIEVED",
                        }
                    )
                except Exception as exc:
                    retrieval_rows.append(
                        {
                            "source_id": candidate.source_id,
                            "url": candidate.url_canonical,
                            "state": "UNAVAILABLE_RUNTIME_OR_SOURCE",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            (args.output / "retrieval_receipts.json").write_text(
                json.dumps(retrieval_rows, ensure_ascii=False, indent=2) + "\n"
            )

    blocked_sources = [r for r in source_receipts if r["state"].startswith(("BLOCKED", "UNRESOLVED", "UNAVAILABLE"))]
    snapshot = {
        "snapshot_version": "2.0.0",
        "created_utc": utc_now(),
        "registry_version": registry.get("registry_version"),
        "source_count": len(source_receipts),
        "candidate_count": len(all_candidates),
        "source_receipts": source_receipts,
        "blocked_or_unresolved_source_count": len(blocked_sources),
        "certification_state": "OPEN" if blocked_sources else "CANDIDATE_PENDING_MANIFESTATION_ADJUDICATION",
    }
    (args.output / "discovery_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
