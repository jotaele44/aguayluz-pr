#!/usr/bin/env python3
"""Freeze PRDOH 2025 public notice and build OCR derivatives for 10747/10748.

Source bytes remain authoritative. OCR output is a derived aid for row reconstruction and
must never replace or silently mutate the frozen source manifestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCES = {
    "10746": "https://www.salud.pr.gov/CMS/DOWNLOAD/10746",
    "10747": "https://www.salud.pr.gov/CMS/DOWNLOAD/10747",
    "10748": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
}
EXPECTED_SOURCE_SHA256 = {
    "10747": "748529762de1b6661b5484957a7662bd233a37aaf371482cdc14bbf5ac584772",
    "10748": "9886fbed47e9f8a3564167034bedc6bc0a0d653c6f89d81d69f8101ccc3f2603",
}
OCR_SOURCE_IDS = ("10747", "10748")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, target: Path) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AguaYLuz-PR/1.0 Salud-2025-OCR"},
    )
    with urllib.request.urlopen(req, timeout=180) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)
        return {
            "status": getattr(response, "status", None),
            "final_url": response.geturl(),
            "content_type": response.headers.get_content_type(),
            "content_length_header": response.headers.get("Content-Length"),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
        }


def pdfinfo(path: Path) -> dict[str, str]:
    output = subprocess.run(
        ["pdfinfo", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    result: dict[str, str] = {}
    for line in output.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def canonicalize_bbox(bbox_path: Path, geometry_path: Path) -> dict[str, Any]:
    """Strip incidental XHTML/PDF metadata and freeze ordered OCR word geometry."""
    root = ET.parse(bbox_path).getroot()
    pages: list[dict[str, Any]] = []
    for page_index, page in enumerate(
        [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "page"],
        start=1,
    ):
        words = []
        for word in page.iter():
            if word.tag.rsplit("}", 1)[-1] != "word":
                continue
            words.append(
                {
                    "text": "".join(word.itertext()),
                    "xMin": word.attrib.get("xMin"),
                    "yMin": word.attrib.get("yMin"),
                    "xMax": word.attrib.get("xMax"),
                    "yMax": word.attrib.get("yMax"),
                }
            )
        pages.append(
            {
                "page": page_index,
                "width": page.attrib.get("width"),
                "height": page.attrib.get("height"),
                "words": words,
            }
        )
    payload = json.dumps(
        {"schema_version": "aguayluz.ocr_word_geometry/v1", "pages": pages},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    geometry_path.write_bytes(payload)
    return {
        "ocr_geometry_file": geometry_path.name,
        "ocr_geometry_sha256": hashlib.sha256(payload).hexdigest(),
        "ocr_geometry_bytes": len(payload),
        "ocr_geometry_pages": len(pages),
        "ocr_geometry_words": sum(len(page["words"]) for page in pages),
    }


def ocr_pdf(source: Path, derived_root: Path, sid: str) -> dict[str, Any]:
    derived_root.mkdir(parents=True, exist_ok=True)
    ocr_pdf_path = derived_root / f"salud_{sid}_ocr.pdf"
    sidecar_path = derived_root / f"salud_{sid}_ocr.txt"
    subprocess.run(
        [
            "ocrmypdf",
            "--force-ocr",
            "--rotate-pages",
            "--deskew",
            "--language",
            "spa+eng",
            "--optimize",
            "1",
            "--sidecar",
            str(sidecar_path),
            str(source),
            str(ocr_pdf_path),
        ],
        check=True,
    )
    bbox_path = derived_root / f"salud_{sid}_ocr_bbox.html"
    subprocess.run(
        ["pdftotext", "-bbox-layout", str(ocr_pdf_path), str(bbox_path)],
        check=True,
    )
    geometry_path = derived_root / f"salud_{sid}_ocr_geometry.json"
    geometry = canonicalize_bbox(bbox_path, geometry_path)
    info = pdfinfo(ocr_pdf_path)
    return {
        "derived_kind": "OCR_TEXT_LAYER_WITH_WORD_GEOMETRY",
        "source_record_id": sid,
        "source_byte_sha256": sha256_file(source),
        "ocr_pdf_file": ocr_pdf_path.name,
        "ocr_pdf_sha256": sha256_file(ocr_pdf_path),
        "ocr_pdf_bytes": ocr_pdf_path.stat().st_size,
        "ocr_pages": int(info["Pages"]),
        "ocr_text_file": sidecar_path.name,
        "ocr_text_sha256": sha256_file(sidecar_path),
        "ocr_text_bytes": sidecar_path.stat().st_size,
        "ocr_bbox_file": bbox_path.name,
        "ocr_bbox_sha256": sha256_file(bbox_path),
        "ocr_bbox_bytes": bbox_path.stat().st_size,
        **geometry,
        "ocr_language": "spa+eng",
        "ocr_rotation": "AUTO",
        "ocr_deskew": True,
        "authority": "DERIVED_NON_AUTHORITATIVE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    root = args.output_root
    raw_root = root / "raw"
    derived_root = root / "derived"
    raw_root.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()

    frozen = []
    paths: dict[str, Path] = {}
    for sid, url in SOURCES.items():
        print(f"FREEZE SALUD {sid}", flush=True)
        path = raw_root / f"salud_{sid}.pdf"
        http = download(url, path)
        if path.read_bytes()[:4] != b"%PDF":
            raise RuntimeError(f"{sid} did not resolve to PDF bytes")
        digest = sha256_file(path)
        expected = EXPECTED_SOURCE_SHA256.get(sid)
        if expected is not None and digest != expected:
            raise RuntimeError(
                f"{sid} source drift: expected {expected}, observed {digest}"
            )
        info = pdfinfo(path)
        frozen.append(
            {
                "source_record_id": sid,
                "source_url": url,
                "retrieved_at_utc": retrieved_at,
                "sha256": digest,
                "bytes": path.stat().st_size,
                "pages": int(info["Pages"]),
                "pdfinfo": info,
                "http": http,
                "source_identity_state": (
                    "MATCHES_PRIOR_FROZEN_MANIFESTATION"
                    if expected is not None
                    else "NEWLY_FROZEN"
                ),
            }
        )
        paths[sid] = path

    derived = [ocr_pdf(paths[sid], derived_root, sid) for sid in OCR_SOURCE_IDS]

    receipt = {
        "schema_version": "aguayluz.prdoh_salud_2025_ocr/v1",
        "retrieved_at_utc": retrieved_at,
        "source": {
            "source": len(SOURCES),
            "frozen": len(frozen),
            "excluded": 0,
            "unresolved": 0,
            "accounted": len(frozen),
            "delta": len(SOURCES) - len(frozen),
            "state": "PASS" if len(frozen) == len(SOURCES) else "FAIL",
            "artifacts": frozen,
        },
        "derived_ocr": derived,
        "row_denominator_state": "OPEN_OCR_READY_ROW_RECONSTRUCTION_REQUIRED",
        "source_universe_completeness_claimed": False,
        "guardrails": [
            "Source PDF bytes are authoritative; OCR output is derived evidence only.",
            "10747/10748 must match the previously frozen byte SHA-256 values.",
            "OCR availability does not certify row extraction or row-to-SDWIS identity.",
            "No violation, exceedance, advisory, or exposure is inferred from OCR alone.",
        ],
    }
    (root / "ocr_source_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
