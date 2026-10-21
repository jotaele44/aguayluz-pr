#!/usr/bin/env python3
"""Acquire and freeze the official PRDOH 2025 drinking-water publication family."""
from __future__ import annotations

import argparse
import json
import urllib.request
from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader

SOURCES = {
    "10746": "https://www.salud.pr.gov/CMS/DOWNLOAD/10746",
    "10747": "https://www.salud.pr.gov/CMS/DOWNLOAD/10747",
    "10748": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AguaYLuz-PR/1.0 source-freeze"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise ValueError(f"source is not a PDF: {url}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    root = args.output_root
    raw = root / "raw"
    text_root = root / "text"
    raw.mkdir(parents=True, exist_ok=True)
    text_root.mkdir(parents=True, exist_ok=True)

    entries = []
    for source_id, url in SOURCES.items():
        data = fetch(url)
        digest = sha256(data).hexdigest()
        pdf_path = raw / f"{source_id}-{digest}.pdf"
        pdf_path.write_bytes(data)

        reader = PdfReader(str(pdf_path))
        pages = []
        full_text_parts = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            full_text_parts.append(text)
            pages.append(
                {
                    "page": index,
                    "text_chars": len(text),
                    "text_sha256": sha256(text.encode("utf-8")).hexdigest(),
                }
            )

        full_text = "\n\f\n".join(full_text_parts)
        text_path = text_root / f"{source_id}.txt"
        text_path.write_text(full_text, encoding="utf-8")
        entries.append(
            {
                "source_record_id": source_id,
                "source_url": url,
                "byte_length": len(data),
                "byte_sha256": digest,
                "page_count": len(reader.pages),
                "text_chars": len(full_text),
                "text_sha256": sha256(full_text.encode("utf-8")).hexdigest(),
                "pdf_file": str(pdf_path.relative_to(root)),
                "text_file": str(text_path.relative_to(root)),
                "pages": pages,
            }
        )

    manifest = {
        "schema_version": "aguayluz.prdoh_salud_2025_source_freeze/v1",
        "source_count": len(entries),
        "sources": entries,
        "source_arithmetic": {
            "source": len(SOURCES),
            "frozen": len(entries),
            "excluded": 0,
            "unresolved": 0,
            "accounted": len(entries),
            "delta": len(SOURCES) - len(entries),
            "state": "PASS" if len(entries) == len(SOURCES) else "FAIL",
        },
        "scope_note": "Byte/text freeze only. No row-level completeness claim is made here.",
    }
    (root / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
