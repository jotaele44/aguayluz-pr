from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import urlsplit
import zipfile

import httpx

from aguayluz.usace_corpus import canonicalize_usace_url, utc_now

BINARY_EXTENSIONS = {".pdf", ".zip", ".kmz", ".docx", ".xlsx", ".pptx", ".doc", ".xls"}


@dataclass(frozen=True)
class ManifestationReceipt:
    source_id: str
    url: str
    retrieved_utc: str
    status_code: int
    content_type: str | None
    byte_count: int
    sha256: str
    final_url: str
    output_path: str
    signature_state: str


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _suffix(url: str) -> str:
    return Path(urlsplit(url).path).suffix.casefold()


def validate_payload_signature(url: str, payload: bytes, content_type: str | None) -> str:
    """Reject silent HTML/login/error payloads before they can become frozen binary artifacts."""
    suffix = _suffix(url)
    stripped = payload[:512].lstrip().lower()
    if not payload:
        raise ValueError("empty payload")
    if suffix in BINARY_EXTENSIONS and (
        stripped.startswith(b"<html") or stripped.startswith(b"<!doctype html")
    ):
        raise ValueError("binary-looking URL returned HTML payload")
    if suffix == ".pdf" and not payload.startswith(b"%PDF-"):
        raise ValueError("PDF URL lacks %PDF- signature")
    if suffix in {".zip", ".kmz", ".docx", ".xlsx", ".pptx"} and not payload.startswith(
        (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    ):
        raise ValueError("ZIP-family URL lacks PK signature")
    if suffix in {".doc", ".xls"} and not payload.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise ValueError("OLE document URL lacks compound-file signature")
    return "PASS_SIGNATURE"


def download_manifestation(
    client: httpx.Client,
    url: str,
    *,
    source_id: str,
    output_dir: Path,
    filename: str | None = None,
) -> ManifestationReceipt:
    """Atomically freeze one manifestation, retaining same-name/different-byte variants."""
    canonical = canonicalize_usace_url(url)
    response = client.get(canonical, follow_redirects=True)
    response.raise_for_status()
    payload = response.content
    signature_state = validate_payload_signature(
        str(response.url), payload, response.headers.get("content-type")
    )
    digest = sha256_bytes(payload)
    name = filename or Path(urlsplit(str(response.url)).path).name or f"{digest}.bin"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / safe
    if final.exists():
        existing = sha256_bytes(final.read_bytes())
        if existing != digest:
            final = output_dir / f"{final.stem}__{digest[:12]}{final.suffix}"
    if not final.exists():
        fd, temp_path = tempfile.mkstemp(prefix=".partial-", dir=output_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, final)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    receipt = ManifestationReceipt(
        source_id=source_id,
        url=canonical,
        retrieved_utc=utc_now(),
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        byte_count=len(payload),
        sha256=digest,
        final_url=str(response.url),
        output_path=str(final),
        signature_state=signature_state,
    )
    final.with_suffix(final.suffix + ".receipt.json").write_text(
        json.dumps(asdict(receipt), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt


def zip_member_manifest(payload: bytes) -> list[dict[str, Any]]:
    """Freeze archive member PATH + UNCOMPRESSED_SIZE + SHA256, preserving duplicate paths."""
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for index, info in enumerate(archive.infolist()):
            if info.is_dir():
                continue
            member = archive.read(info)
            rows.append(
                {
                    "member_index": index,
                    "path": info.filename,
                    "uncompressed_size": len(member),
                    "sha256": sha256_bytes(member),
                }
            )
    rows.sort(key=lambda row: (row["path"], row["member_index"]))
    return rows


def classify_zip_identity(a: bytes, b: bytes) -> str:
    """Classify archive byte/payload identity without equating different outer hashes."""
    if sha256_bytes(a) == sha256_bytes(b):
        return "BYTE_IDENTICAL"
    try:
        left = zip_member_manifest(a)
        right = zip_member_manifest(b)
    except zipfile.BadZipFile:
        return "UNRESOLVED"
    left_paths = Counter(
        (row["path"], row["uncompressed_size"], row["sha256"]) for row in left
    )
    right_paths = Counter(
        (row["path"], row["uncompressed_size"], row["sha256"]) for row in right
    )
    if left_paths == right_paths:
        return "PURE_RECOMPRESSION"
    left_payloads = Counter((row["uncompressed_size"], row["sha256"]) for row in left)
    right_payloads = Counter((row["uncompressed_size"], row["sha256"]) for row in right)
    if left_payloads == right_payloads:
        return "SAME_PAYLOADS_DIFFERENT_PATHS"
    return "DISTINCT_PAYLOADS"
