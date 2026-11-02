#!/usr/bin/env python3
"""Manual, bounded source acquisition; never promotes source rows to canonical data.

No scheduling or unattended deployment until the security and provenance gates pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from aguayluz.hydro_intelligence.acquisition import fetch_artifact
from aguayluz.hydro_intelligence.discovery import (
    acquire_with_retry,
    discover_links,
    freeze_result_log,
)

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "config" / "hydro_intelligence_sources.v1.json"
SUFFIX = {"xlsx": (".xlsx",), "zip": (".zip",), "pdf": (".pdf",)}


def source_record(registry: dict, source_id: str) -> dict:
    matches = [s for s in registry["source_families"] if s["source_id"] == source_id]
    if len(matches) != 1:
        raise ValueError("Source ID not exactly registered")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--artifact-url")
    parser.add_argument("--data-root", type=Path,
                        default=REPO / "data" / "hydro_intelligence")
    args = parser.parse_args(argv)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    source = source_record(registry, args.source_id)
    host = urlparse(source["index_url"]).hostname
    if not host:
        raise ValueError("Source registry contains invalid host")
    allowed_hosts = {host}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if args.artifact_url:
        result = acquire_with_retry(
            args.data_root / "raw", args.source_id, args.artifact_url,
            allowed_hosts=allowed_hosts,
        )
        output = [result]
    else:
        raw, _media = fetch_artifact(source["index_url"], allowed_hosts=allowed_hosts)
        kind = source["artifact_type"]
        if kind not in SUFFIX:
            raise ValueError("Discovery-only adapter required for this source type")
        candidates = discover_links(
            args.source_id, source["index_url"], raw,
            allowed_hosts, SUFFIX[kind],
        )
        output = [{
            "state": "DISCOVERY_ONLY",
            "index_sha256": hashlib.sha256(raw).hexdigest(),
            "index_url": source["index_url"],
            "candidate_count": len(candidates),
            "candidates": [candidate.artifact_url for candidate in candidates],
            "completeness": "NOT_CLAIMED",
        }]
    receipt_path = args.data_root / "runs" / f"{args.source_id}-{stamp}.json"
    receipt_hash = freeze_result_log(receipt_path, output)
    print(json.dumps({"receipt_path": str(receipt_path), "sha256": receipt_hash,
                      "result": output}, sort_keys=True))
    if any(row["state"] == "QUARANTINED_NOT_PROMOTED" for row in output):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
