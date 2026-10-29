"""Fail-closed, source-agnostic hydro artifact acquisition primitives.

Infrastructure only: no canonical observation is promoted by this module.
Sources are constrained to HTTPS and configured hostnames.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Redirect requires explicit source review")

MAX_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class ArtifactReceipt:
    source_id: str
    url: str
    sha256: str
    byte_count: int
    fetched_at: str
    media_type: str
    state: str = "RAW_FROZEN_NOT_PARSED"


def validate_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only unsigned HTTPS URLs are permitted")
    if parsed.hostname.lower() not in allowed_hosts:
        raise ValueError("Source hostname is not in allowlist")
    if parsed.port not in (None, 443):
        raise ValueError("Nonstandard source port is not permitted")


def persist_bytes(root: Path, source_id: str, url: str, data: bytes,
                  media_type: str = "application/octet-stream",
                  fetched_at: str | None = None) -> ArtifactReceipt:
    if not source_id or not all(c.isalnum() or c in "_-" for c in source_id):
        raise ValueError("Invalid source identifier")
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Empty or oversized artifact")
    digest = hashlib.sha256(data).hexdigest()
    receipt = ArtifactReceipt(
        source_id=source_id, url=url, sha256=digest, byte_count=len(data),
        fetched_at=fetched_at or datetime.now(timezone.utc).isoformat(),
        media_type=media_type,
    )
    folder = root / source_id / digest[:2]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / digest
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError("Stored artifact does not match its digest")
    else:
        fd, tmp = tempfile.mkstemp(dir=folder)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(tmp, target)  # atomic no-clobber; concurrent writers cannot replace frozen bytes
            except FileExistsError:
                if target.read_bytes() != data:
                    raise ValueError("Concurrent artifact differs from expected bytes")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    # One receipt per identical artifact. Historical release metadata belongs
    # to a separate versioned discovery manifest, not an overwritten receipt.
    receipt_path = folder / (digest + ".receipt.json")
    if not receipt_path.exists():
        receipt_path.write_text(json.dumps(asdict(receipt), sort_keys=True, indent=2) + "\n")
    return receipt


def fetch_artifact(url: str, *, allowed_hosts: set[str], timeout: float = 30,
                   max_bytes: int = MAX_BYTES) -> tuple[bytes, str]:
    validate_url(url, allowed_hosts)
    request = Request(url, headers={"User-Agent": "AguaYLuz-HydroEvidence/1.0"})
    # No automatic promotion; caller must validate source format and schema.
    with build_opener(RejectRedirects()).open(request, timeout=timeout) as response:
        validate_url(response.geturl(), allowed_hosts)
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError("Source payload exceeds size limit")
        data = response.read(max_bytes + 1)
        if not data or len(data) > max_bytes:
            raise ValueError("Source response empty or oversized")
        return data, response.headers.get("Content-Type", "application/octet-stream")


def acquire(root: Path, source_id: str, url: str, *,
            allowed_hosts: set[str], timeout: float = 30) -> ArtifactReceipt:
    try:
        raw, content_type = fetch_artifact(url, allowed_hosts=allowed_hosts, timeout=timeout)
        return persist_bytes(root, source_id, url, raw, content_type)
    except Exception:
        # A failed acquisition is NEVER a zero-generation observation.
        # Failure classification/retry policy is owned by the scheduler.
        raise
