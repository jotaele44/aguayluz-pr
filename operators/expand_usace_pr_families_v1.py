#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from aguayluz.usace_family import (
    FamilyLink,
    discover_family_links,
    family_arithmetic,
    is_direct_manifestation,
    next_family_pages,
)
from aguayluz.usace_manifestation import download_manifestation
from aguayluz.usace_corpus import utc_now


def read_candidates(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
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
    parser = argparse.ArgumentParser(description="Bounded USACE report-family expansion")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--download-direct", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.max_depth <= 10:
        raise SystemExit("--max-depth must be within 0..10")

    roots = read_candidates(args.candidates)
    args.output.mkdir(parents=True, exist_ok=True)
    all_links: list[FamilyLink] = []
    dispositions: dict[str, str] = {}
    page_receipts: list[dict[str, object]] = []
    visited: set[str] = set()
    queue: list[tuple[str, int, str]] = []

    for row in roots:
        url = row.get("url_canonical") or row.get("url_raw") or ""
        source_id = row.get("source_id") or "UNRESOLVED_SOURCE"
        if not url:
            continue
        if is_direct_manifestation(url):
            dispositions.setdefault(url, "UNRESOLVED")
        else:
            queue.append((url, 0, source_id))

    headers = {"User-Agent": "aguayluz-pr-usace-family-expander/1.0 (+public research corpus)"}
    with httpx.Client(
        timeout=httpx.Timeout(60, connect=20), headers=headers, follow_redirects=True
    ) as client:
        while queue:
            page_url, depth, source_id = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            if depth > args.max_depth:
                continue
            try:
                response = client.get(page_url)
                response.raise_for_status()
            except Exception as exc:
                page_receipts.append(
                    {
                        "url": page_url,
                        "depth": depth,
                        "state": "UNAVAILABLE_RUNTIME_OR_SOURCE",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            content_type = str(response.headers.get("content-type") or "")
            if "html" not in content_type.casefold() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
                page_receipts.append(
                    {
                        "url": page_url,
                        "depth": depth,
                        "http_status": response.status_code,
                        "content_type": content_type,
                        "state": "UNRESOLVED_NONHTML_DETAIL_PAGE",
                    }
                )
                continue
            links = discover_family_links(response.text, parent_url=page_url, depth=depth + 1)
            all_links.extend(links)
            page_receipts.append(
                {
                    "url": page_url,
                    "depth": depth,
                    "http_status": response.status_code,
                    "content_type": content_type,
                    "discovered_link_count": len(links),
                    "state": "PASS_PAGE_EXPANSION",
                }
            )
            for link in links:
                if link.kind == "DIRECT_MANIFESTATION":
                    dispositions.setdefault(link.child_url_canonical, "UNRESOLVED")
                    if args.download_direct:
                        try:
                            download_manifestation(
                                client,
                                link.child_url_canonical,
                                source_id=source_id,
                                output_dir=args.output / "raw",
                            )
                            dispositions[link.child_url_canonical] = "RETRIEVED"
                        except Exception:
                            dispositions[link.child_url_canonical] = "UNAVAILABLE"
            current_host = urlsplit(page_url).netloc
            for child in next_family_pages(links, current_host=current_host, visited=visited):
                queue.append((child, depth + 1, source_id))

    link_rows = [asdict(row) for row in all_links]
    for row in link_rows:
        row["disposition"] = dispositions.get(str(row["child_url_canonical"]), "UNRESOLVED")
    write_csv(args.output / "family_edges.csv", link_rows)
    arithmetic = family_arithmetic(all_links, dispositions)
    snapshot = {
        "snapshot_version": "1.0.0",
        "created_utc": utc_now(),
        "root_candidate_count": len(roots),
        "visited_detail_page_count": len(visited),
        "family_edge_count": len(all_links),
        "page_receipts": page_receipts,
        "family_arithmetic": arithmetic,
        "certification_state": (
            "PASS_FAMILY_ZERO_RESIDUE"
            if arithmetic["unresolved"] == 0 and arithmetic["unavailable"] == 0
            else "OPEN_FAMILY_RESIDUE"
        ),
    }
    (args.output / "family_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
