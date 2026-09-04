#!/usr/bin/env python3
"""Freeze configured ArcGIS water-monitoring sources with raw-byte provenance.

The snapshotter is deliberately restartable. Existing snapshot directories are reused
unless --new-snapshot is supplied; downstream failures therefore do not silently
redownload mutable sources and change the evidentiary input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "water_monitoring_sources.json"
DEFAULT_OUTPUT = ROOT / "data" / "raw" / "water_monitoring"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def latest_snapshot(source_root: Path) -> Path | None:
    candidates = sorted(path for path in source_root.glob("20*T*Z") if path.is_dir())
    return candidates[-1] if candidates else None


def fetch_bytes(client: httpx.Client, url: str, params: dict[str, Any]) -> tuple[bytes, str]:
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.content, str(response.url)


def freeze_arcgis_source(
    client: httpx.Client,
    source: dict[str, Any],
    output_root: Path,
    *,
    new_snapshot: bool,
) -> Path:
    source_root = output_root / source["source_id"]
    source_root.mkdir(parents=True, exist_ok=True)
    previous = latest_snapshot(source_root)
    if previous and not new_snapshot:
        return previous

    retrieval_utc = utc_stamp()
    snapshot_dir = source_root / retrieval_utc
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    layer_url = source["url"].rstrip("/")
    metadata_bytes, metadata_url = fetch_bytes(client, layer_url, {"f": "json"})
    (snapshot_dir / "layer_metadata.raw.json").write_bytes(metadata_bytes)
    metadata = json.loads(metadata_bytes)
    page_size = int(metadata.get("maxRecordCount") or 2000)
    query_url = f"{layer_url}/query"
    base_query = dict(source["query"])

    offset = 0
    page_manifests: list[dict[str, Any]] = []
    all_features: list[dict[str, Any]] = []
    while True:
        params = dict(base_query)
        params["resultOffset"] = offset
        params["resultRecordCount"] = page_size
        payload, resolved_url = fetch_bytes(client, query_url, params)
        page = json.loads(payload)
        features = page.get("features")
        if not isinstance(features, list):
            raise RuntimeError(f"{source['source_id']} page {offset} lacks a features array")

        page_name = f"page_{offset:08d}.raw.geojson"
        (snapshot_dir / page_name).write_bytes(payload)
        page_manifests.append(
            {
                "offset": offset,
                "record_count": len(features),
                "path": page_name,
                "sha256": sha256_bytes(payload),
                "resolved_url": resolved_url,
            }
        )
        all_features.extend(features)
        if len(features) < page_size:
            break
        offset += page_size

    combined = {"type": "FeatureCollection", "features": all_features}
    combined_bytes = json.dumps(
        combined, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    combined_path = snapshot_dir / "combined.canonical.geojson"
    combined_path.write_bytes(combined_bytes)

    stable_candidates = source.get("stable_id_candidates", [])
    stable_ids: list[str] = []
    if stable_candidates:
        for feature in all_features:
            props = feature.get("properties") or {}
            value = next((props.get(key) for key in stable_candidates if props.get(key)), None)
            if value is None:
                raise RuntimeError(
                    f"{source['source_id']} feature lacks stable ID candidates {stable_candidates}"
                )
            stable_ids.append(str(value))
        if len(set(stable_ids)) != len(stable_ids):
            raise RuntimeError(f"{source['source_id']} has duplicate selected stable IDs")

    manifest = {
        "schema_version": "water_monitoring_snapshot_v1",
        "source_id": source["source_id"],
        "authority": source["authority"],
        "source_url": source["url"],
        "metadata_resolved_url": metadata_url,
        "retrieval_utc": retrieval_utc,
        "source_crs": source.get("source_crs"),
        "requested_output_crs": "EPSG:4326" if base_query.get("outSR") == 4326 else None,
        "geometry_type": source.get("geometry_type"),
        "raw_metadata_sha256": sha256_bytes(metadata_bytes),
        "pages": page_manifests,
        "page_count": len(page_manifests),
        "feature_count": len(all_features),
        "stable_id_candidates": stable_candidates,
        "stable_id_unique_count": len(set(stable_ids)) if stable_ids else None,
        "combined_serialization": "UTF-8 JSON; sort_keys=true; separators=(',', ':')",
        "combined_sha256": sha256_bytes(combined_bytes),
    }
    (snapshot_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return snapshot_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", help="Source ID to snapshot; repeatable")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--new-snapshot", action="store_true")
    args = parser.parse_args()

    registry = load_registry()
    requested = set(args.source or [])
    sources = [
        source
        for source in registry["sources"]
        if source.get("query") and (not requested or source["source_id"] in requested)
    ]
    unknown = requested - {source["source_id"] for source in sources}
    if unknown:
        raise SystemExit(f"Unknown or non-queryable source IDs: {sorted(unknown)}")

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for source in sources:
            snapshot = freeze_arcgis_source(
                client,
                source,
                args.output,
                new_snapshot=args.new_snapshot,
            )
            print(f"{source['source_id']}: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
