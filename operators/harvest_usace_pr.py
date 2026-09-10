#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

import httpx

from aguayluz.usace_corpus import (
    SourceSpec,
    discover_contentdm_search,
    discover_saj_environmental_documents,
    download_url,
    utc_now,
)


def load_registry(path: Path) -> list[SourceSpec]:
    payload = json.loads(path.read_text())
    return [SourceSpec(**row) for row in payload["sources"] if row.get("enabled", True)]


def write_candidates(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest bounded Puerto Rico USACE hydospatial corpus")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    sources = load_registry(args.registry)
    args.output.mkdir(parents=True, exist_ok=True)
    candidates = []
    snapshot = {"started_utc": utc_now(), "sources": [], "candidate_count": 0}

    timeout = httpx.Timeout(60.0, connect=20.0)
    headers = {"User-Agent": "aguayluz-pr-usace-harvester/1.0 (+research corpus)"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for source in sources:
            state = {"source_id": source.source_id, "url": source.url, "state": "OPEN"}
            try:
                response = client.get(source.url)
                response.raise_for_status()
                state["http_status"] = response.status_code
                state["content_type"] = response.headers.get("content-type")
                if source.adapter == "saj_environmental_documents":
                    found = discover_saj_environmental_documents(
                        response.text, source_id=source.source_id, source_page=source.url
                    )
                elif source.adapter == "contentdm_api":
                    found = discover_contentdm_search(
                        response.json(), source_id=source.source_id, source_page=source.url
                    )
                else:
                    found = []
                    state["state"] = "DISCOVERY_ADAPTER_NOT_IMPLEMENTED"
                candidates.extend(found)
                state["candidate_count"] = len(found)
                if state["state"] == "OPEN":
                    state["state"] = "PASS_DISCOVERY"
            except Exception as exc:
                state["state"] = "UNAVAILABLE"
                state["error"] = f"{type(exc).__name__}: {exc}"
            snapshot["sources"].append(state)

        rows = [asdict(candidate) for candidate in candidates]
        write_candidates(args.output / "candidates.csv", rows)
        snapshot["candidate_count"] = len(rows)
        (args.output / "discovery_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        )

        if args.download:
            receipts = []
            for candidate in candidates:
                try:
                    receipt = download_url(
                        client,
                        candidate.url_canonical,
                        source_id=candidate.source_id,
                        output_dir=args.output / "raw",
                    )
                    receipts.append(asdict(receipt))
                except Exception as exc:
                    receipts.append(
                        {
                            "source_id": candidate.source_id,
                            "url": candidate.url_canonical,
                            "state": "UNAVAILABLE",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            (args.output / "retrieval_receipts.json").write_text(
                json.dumps(receipts, ensure_ascii=False, indent=2) + "\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
