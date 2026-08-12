#!/usr/bin/env python3
"""Ingest USGS NIMS camera metadata and recent image listings for Puerto Rico gages.

No images are downloaded and no computer-vision inference is performed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from aguayluz.usgs_water_api import (  # noqa: E402
    NIMS_ROOT,
    api_headers,
    read_jsonl,
    source_receipt,
    stable_hash,
    write_jsonl,
)


def site_ids_from_assets(path: Path) -> list[str]:
    sites: set[str] = set()
    for row in read_jsonl(path):
        asset_id = str(row.get("asset_id") or "")
        if asset_id.startswith("USGS_"):
            sites.add(asset_id.removeprefix("USGS_"))
    return sorted(sites)


def _list(document: Any) -> list[dict]:
    if isinstance(document, list):
        return [row for row in document if isinstance(row, dict)]
    if isinstance(document, dict):
        for key in ("items", "data", "cameras", "files"):
            if isinstance(document.get(key), list):
                return [row for row in document[key] if isinstance(row, dict)]
    return []


def camera_rows(documents: list[Any]) -> list[dict]:
    rows: dict[str, dict] = {}
    for document in documents:
        for camera in _list(document):
            cam_id = str(camera.get("camId") or camera.get("cameraId") or camera.get("id") or "")
            if not cam_id:
                continue
            rows[cam_id] = {
                "camera_id": cam_id,
                "camera_name": camera.get("camName") or camera.get("name"),
                "site_no": str(camera.get("siteId") or camera.get("site_no") or ""),
                "newest_image_at": camera.get("newestImageDT") or camera.get("newest_image_at"),
                "overlay_dir": camera.get("overlayDir"),
                "thumbnail_dir": camera.get("thumbDir"),
                "small_image_dir": camera.get("smallDir"),
                "timelapse_dir": camera.get("tlDir"),
                "source_ref": f"{NIMS_ROOT}/cameras",
                "evidence_tier": "T1",
            }
    return [rows[key] for key in sorted(rows)]


def image_rows(camera: dict, document: Any) -> list[dict]:
    cam_id = camera["camera_id"]
    base = str(camera.get("overlay_dir") or "")
    rows: list[dict] = []
    items = document if isinstance(document, list) else _list(document)
    for item in items:
        if isinstance(item, str):
            filename, timestamp, size = item, None, None
        else:
            filename = str(item.get("filename") or item.get("name") or "")
            timestamp = item.get("timestamp")
            size = item.get("fs") or item.get("size")
        if not filename:
            continue
        rows.append(
            {
                "image_id": f"USGS_NIMS_IMG_{stable_hash(cam_id, filename)[:24]}",
                "camera_id": cam_id,
                "site_no": camera.get("site_no"),
                "filename": filename,
                "timestamp": timestamp,
                "file_size": size,
                "image_url": f"{base}{filename}" if base else None,
                "source_ref": f"{NIMS_ROOT}/listFiles?camId={cam_id}",
                "evidence_tier": "T1",
                "visual_inference_performed": False,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src-cameras", type=Path)
    parser.add_argument("--src-files", type=Path)
    parser.add_argument("--assets", type=Path, default=Path("data/utility_assets.jsonl"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--cameras-out", type=Path, default=Path("data/usgs_nims_cameras.jsonl"))
    parser.add_argument("--images-out", type=Path, default=Path("data/usgs_nims_images.jsonl"))
    parser.add_argument("--receipt", type=Path, default=Path("data/usgs_nims_receipt.json"))
    args = parser.parse_args()
    live = args.src_cameras is None
    try:
        if args.src_cameras:
            camera_docs = [json.loads(args.src_cameras.read_text(encoding="utf-8"))]
        else:
            sites = site_ids_from_assets(args.assets)
            camera_docs = []
            with httpx.Client(timeout=180, follow_redirects=True) as client:
                for site in sites:
                    response = client.get(
                        f"{NIMS_ROOT}/cameras",
                        params={"siteId": site},
                        headers=api_headers(),
                    )
                    response.raise_for_status()
                    camera_docs.append(response.json())
        cameras = camera_rows(camera_docs)
        images: list[dict] = []
        if args.src_files:
            file_document = json.loads(args.src_files.read_text(encoding="utf-8"))
            for camera in cameras:
                images.extend(image_rows(camera, file_document))
        elif live:
            with httpx.Client(timeout=180, follow_redirects=True) as client:
                for camera in cameras:
                    response = client.get(
                        f"{NIMS_ROOT}/listFiles",
                        params={
                            "camId": camera["camera_id"],
                            "limit": max(1, min(args.limit, 50000)),
                            "rawItem": "true",
                        },
                        headers=api_headers(),
                    )
                    response.raise_for_status()
                    images.extend(image_rows(camera, response.json()))
    except Exception as exc:  # noqa: BLE001
        print(f"NIMS fetch failed: {exc}", file=sys.stderr)
        return 1

    write_jsonl(args.cameras_out, cameras)
    write_jsonl(args.images_out, sorted(images, key=lambda row: row["image_id"]))
    receipt = source_receipt(
        category="national_imagery_management_system",
        source_url=NIMS_ROOT,
        rows_written=len(cameras) + len(images),
        skipped={"computer_vision_inferences": 0},
        live=live,
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(cameras)} cameras and {len(images)} image-listing rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
