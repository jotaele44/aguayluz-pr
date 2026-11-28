#!/usr/bin/env python3
"""Create immutable page-level evidence for the Puerto Rico Salud 2025 water reports.

This tool deliberately stops before row admission.  The authoritative PDF bytes are
verified against the Oct. 16 frozen manifestations, every page is rendered and hashed,
and optional extraction candidates are validated against those exact page identities.

OCR, vision, or manual extraction can therefore be used as a *candidate generator*
without silently becoming canonical WATER_HEALTH evidence.  A candidate must remain
CANDIDATE_UNVERIFIED until a separate review step explicitly verifies it against the
page image.  This tool emits zero canonical hazard records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCES: dict[str, dict[str, Any]] = {
    "10747": {
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10747",
        "sha256": "748529762de1b6661b5484957a7662bd233a37aaf371482cdc14bbf5ac584772",
        "pages": 40,
        "role": "ANNUAL_VIOLATIONS_REPORT_2025",
        "text_layer_state": "RENDER_REQUIRED_TEXT_LAYER_UNTRUSTED",
    },
    "10748": {
        "url": "https://www.salud.pr.gov/CMS/DOWNLOAD/10748",
        "sha256": "9886fbed47e9f8a3564167034bedc6bc0a0d653c6f89d81d69f8101ccc3f2603",
        "pages": 33,
        "role": "ANEJOS_APENDICES_2025",
        "text_layer_state": "RENDER_REQUIRED_IMAGE_ONLY",
    },
}
ALLOWED_METHODS = {
    "MANUAL_PAGE_REVIEW",
    "OCR_ASSISTED_REVIEW",
    "VISION_ASSISTED_REVIEW",
}
CANDIDATE_STATE = "CANDIDATE_UNVERIFIED"
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def tool_version(command: str) -> str:
    proc = subprocess.run(
        [command, "-v"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (proc.stderr or proc.stdout).strip().splitlines()
    if not output:
        raise RuntimeError(f"cannot determine {command} version")
    return output[0]


def download_pdf(url: str, target: Path) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AguaYLuz-SaludPageEvidence/1.0"},
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=180) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)
        return {
            "final_url": response.geturl(),
            "status": getattr(response, "status", None),
            "content_type": response.headers.get_content_type(),
            "content_length_header": response.headers.get("Content-Length"),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
        }


def pdf_page_count(path: Path) -> int:
    proc = subprocess.run(
        ["pdfinfo", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"pdfinfo did not report Pages for {path}")


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"not a PNG with IHDR: {path}")
    return struct.unpack(">II", header[16:24])


def extract_page_text(path: Path, page_number: int) -> bytes:
    proc = subprocess.run(
        [
            "pdftotext",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-layout",
            "-enc",
            "UTF-8",
            str(path),
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return proc.stdout


def render_page(
    pdf: Path,
    *,
    page_number: int,
    output: Path,
    dpi: int,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="salud-page-") as temp_dir:
        prefix = Path(temp_dir) / "page"
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                "-gray",
                "-png",
                "-r",
                str(dpi),
                str(pdf),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
        rendered = prefix.with_suffix(".png")
        if not rendered.is_file():
            raise RuntimeError(f"render missing for page {page_number} of {pdf}")
        shutil.move(str(rendered), output)

    width, height = png_dimensions(output)
    text = extract_page_text(pdf, page_number)
    return {
        "page_number": page_number,
        "render_file": output.name,
        "render_sha256": sha256_file(output),
        "render_bytes": output.stat().st_size,
        "render_width": width,
        "render_height": height,
        "text_bytes": len(text),
        "text_sha256": sha256_bytes(text),
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} candidate must be an object")
        rows.append(value)
    return rows


def validate_candidate(
    candidate: dict[str, Any],
    *,
    page_lookup: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    candidate_id = candidate.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id is required")

    source_id = str(candidate.get("source_record_id") or "")
    if source_id not in SOURCES:
        raise ValueError(f"{candidate_id}: unsupported source_record_id {source_id!r}")

    pdf_sha = candidate.get("source_pdf_sha256")
    if pdf_sha != SOURCES[source_id]["sha256"]:
        raise ValueError(f"{candidate_id}: source PDF hash mismatch")

    page_number = candidate.get("page_number")
    if not isinstance(page_number, int) or isinstance(page_number, bool):
        raise ValueError(f"{candidate_id}: page_number must be an integer")
    page = page_lookup.get((source_id, page_number))
    if page is None:
        raise ValueError(f"{candidate_id}: page_number is outside the frozen page denominator")

    render_sha = candidate.get("page_render_sha256")
    if not isinstance(render_sha, str) or not HEX64_RE.fullmatch(render_sha):
        raise ValueError(f"{candidate_id}: page_render_sha256 must be lowercase SHA-256")
    if render_sha != page["render_sha256"]:
        raise ValueError(f"{candidate_id}: rendered page hash mismatch")

    method = candidate.get("extraction_method")
    if method not in ALLOWED_METHODS:
        raise ValueError(f"{candidate_id}: unsupported extraction_method {method!r}")

    if candidate.get("state") != CANDIDATE_STATE:
        raise ValueError(
            f"{candidate_id}: state must remain {CANDIDATE_STATE}; this tool cannot verify rows"
        )

    ordinal = candidate.get("row_ordinal_on_page")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        raise ValueError(f"{candidate_id}: row_ordinal_on_page must be a positive integer")

    fields = candidate.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError(f"{candidate_id}: fields must be a non-empty object")

    return {
        "candidate_id": candidate_id,
        "source_record_id": source_id,
        "source_pdf_sha256": pdf_sha,
        "page_number": page_number,
        "page_render_sha256": render_sha,
        "row_ordinal_on_page": ordinal,
        "extraction_method": method,
        "state": CANDIDATE_STATE,
        "fields": fields,
    }


def candidate_receipt(
    candidates: list[dict[str, Any]],
    *,
    page_lookup: dict[tuple[str, int], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_rows: set[tuple[str, int, int]] = set()
    for candidate in candidates:
        row = validate_candidate(candidate, page_lookup=page_lookup)
        if row["candidate_id"] in seen_ids:
            raise ValueError(f"duplicate candidate_id {row['candidate_id']}")
        row_key = (
            row["source_record_id"],
            row["page_number"],
            row["row_ordinal_on_page"],
        )
        if row_key in seen_rows:
            raise ValueError(f"duplicate candidate page-row identity {row_key}")
        seen_ids.add(row["candidate_id"])
        seen_rows.add(row_key)
        validated.append(row)

    accounting = {
        "candidate_source": len(candidates),
        "candidate_unverified": len(validated),
        "candidate_verified": 0,
        "candidate_rejected": 0,
        "accounted": len(validated),
        "delta": len(candidates) - len(validated),
    }
    accounting["state"] = "PASS" if accounting["delta"] == 0 else "FAIL"
    return validated, accounting


def run(
    *,
    output_root: Path,
    source_paths: dict[str, Path],
    dpi: int = 120,
    candidates_path: Path | None = None,
    http_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if dpi < 72 or dpi > 300:
        raise ValueError("dpi must be between 72 and 300")

    generated_at = datetime.now(timezone.utc).isoformat()
    output_root.mkdir(parents=True, exist_ok=True)
    source_receipts: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    page_lookup: dict[tuple[str, int], dict[str, Any]] = {}

    for source_id in sorted(SOURCES):
        spec = SOURCES[source_id]
        source = source_paths[source_id]
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.read_bytes()[:4] != b"%PDF":
            raise ValueError(f"{source_id}: source is not PDF bytes")
        observed_sha = sha256_file(source)
        if observed_sha != spec["sha256"]:
            raise ValueError(
                f"{source_id}: authoritative PDF hash drift "
                f"expected={spec['sha256']} observed={observed_sha}"
            )
        pages = pdf_page_count(source)
        if pages != spec["pages"]:
            raise ValueError(
                f"{source_id}: page denominator drift expected={spec['pages']} observed={pages}"
            )

        render_dir = output_root / "rendered" / source_id
        source_page_rows: list[dict[str, Any]] = []
        for page_number in range(1, pages + 1):
            row = render_page(
                source,
                page_number=page_number,
                output=render_dir / f"page-{page_number:04d}.png",
                dpi=dpi,
            )
            row.update(
                {
                    "source_record_id": source_id,
                    "source_pdf_sha256": observed_sha,
                    "source_role": spec["role"],
                    "text_layer_state": spec["text_layer_state"],
                }
            )
            source_page_rows.append(row)
            page_rows.append(row)
            page_lookup[(source_id, page_number)] = row

        page_manifest_sha = sha256_bytes(canonical_json_bytes(source_page_rows))
        source_receipts.append(
            {
                "source_record_id": source_id,
                "source_url": spec["url"],
                "role": spec["role"],
                "source_pdf_sha256": observed_sha,
                "source_pdf_bytes": source.stat().st_size,
                "expected_pages": spec["pages"],
                "observed_pages": pages,
                "text_layer_state": spec["text_layer_state"],
                "page_manifest_sha256": page_manifest_sha,
                **(
                    {"http": http_metadata[source_id]}
                    if http_metadata and source_id in http_metadata
                    else {}
                ),
            }
        )

    pages_source = sum(int(SOURCES[source_id]["pages"]) for source_id in SOURCES)
    page_accounting = {
        "source": pages_source,
        "retained": len(page_rows),
        "excluded": 0,
        "unresolved": 0,
        "accounted": len(page_rows),
        "delta": pages_source - len(page_rows),
    }
    page_accounting["state"] = "PASS" if page_accounting["delta"] == 0 else "FAIL"
    if page_accounting["state"] != "PASS":
        raise RuntimeError(f"page arithmetic failed: {page_accounting}")

    candidates = read_jsonl(candidates_path) if candidates_path else []
    validated_candidates, candidate_accounting = candidate_receipt(
        candidates,
        page_lookup=page_lookup,
    )

    page_manifest_path = output_root / "salud_2025_page_manifest.jsonl"
    page_manifest_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in page_rows),
        encoding="utf-8",
    )
    candidates_out = output_root / "salud_2025_row_candidates.jsonl"
    candidates_out.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in validated_candidates),
        encoding="utf-8",
    )

    receipt = {
        "schema_version": "aguayluz.salud_2025_page_evidence/v1",
        "generated_at_utc": generated_at,
        "render_dpi": dpi,
        "render_mode": "POPPLER_PDFTOPPM_GRAYSCALE_PNG",
        "render_tool": tool_version("pdftoppm"),
        "text_tool": tool_version("pdftotext"),
        "sources": source_receipts,
        "page_arithmetic": page_accounting,
        "page_manifest_file": page_manifest_path.name,
        "page_manifest_sha256": sha256_file(page_manifest_path),
        "candidate_file": candidates_out.name,
        "candidate_file_sha256": sha256_file(candidates_out),
        "candidate_accounting": candidate_accounting,
        "row_denominator_state": "OPEN_NOT_ENUMERATED",
        "canonical_records_emitted": 0,
        "source_universe_completeness_claimed": False,
        "guardrails": [
            "Rendered page identity is evidence, not a violation-row identity.",
            "OCR, vision, and manual extraction outputs remain CANDIDATE_UNVERIFIED here.",
            "No candidate can be admitted without exact source PDF and rendered-page SHA-256.",
            "This page denominator does not establish the annual-report row denominator.",
            "This tool emits zero canonical hazard records.",
        ],
    }
    (output_root / "salud_2025_page_evidence_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--salud-10747", type=Path)
    parser.add_argument("--salud-10748", type=Path)
    parser.add_argument("--download-official", action="store_true")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--dpi", type=int, default=120)
    args = parser.parse_args()

    supplied = {"10747": args.salud_10747, "10748": args.salud_10748}
    if args.download_official and any(path is not None for path in supplied.values()):
        raise ValueError("--download-official cannot be combined with explicit PDF paths")
    if not args.download_official and any(path is None for path in supplied.values()):
        raise ValueError("provide both Salud PDF paths or use --download-official")

    http_meta: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, Path] = {}
    if args.download_official:
        raw = args.output_root / "raw"
        for source_id, spec in SOURCES.items():
            target = raw / f"salud_{source_id}.pdf"
            http_meta[source_id] = download_pdf(spec["url"], target)
            source_paths[source_id] = target
    else:
        source_paths = {source_id: path for source_id, path in supplied.items() if path is not None}

    receipt = run(
        output_root=args.output_root,
        source_paths=source_paths,
        dpi=args.dpi,
        candidates_path=args.candidates,
        http_metadata=http_meta or None,
    )
    print(
        json.dumps(
            {
                "page_arithmetic": receipt["page_arithmetic"],
                "candidate_accounting": receipt["candidate_accounting"],
                "row_denominator_state": receipt["row_denominator_state"],
                "canonical_records_emitted": receipt["canonical_records_emitted"],
                "page_manifest_sha256": receipt["page_manifest_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
