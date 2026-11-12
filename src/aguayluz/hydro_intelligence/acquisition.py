"""Fail-closed, source-agnostic hydro artifact acquisition primitives.

Infrastructure only: no canonical observation is promoted by this module.
Sources are constrained to HTTPS and configured hostnames.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler


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


def reject_nonpublic_dns(host: str) -> tuple[str, ...]:
    """Return vetted DNS addresses and reject any non-global answer."""
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("DNS resolution failed") from exc
    if not answers:
        raise ValueError("DNS resolution returned no addresses")
    addresses = []
    for answer in answers:
        address = answer[4][0].split("%", 1)[0]
        try:
            valid = ipaddress.ip_address(address).is_global
        except ValueError as exc:
            raise ValueError("DNS returned invalid IP") from exc
        if not valid:
            raise ValueError("DNS returned non-global IP")
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect only to the vetted address; verify TLS against the source host."""

    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self._pinned_address = address

    def connect(self) -> None:
        plain = socket.create_connection((self._pinned_address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(plain, server_hostname=self.host)
        except Exception:
            plain.close()
            raise


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
    if root.is_symlink() or root.parent.is_symlink() or (root / source_id).is_symlink() or folder.is_symlink():
        raise ValueError("Symlinked evidence directory")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / digest
    if target.is_symlink():
        raise ValueError("Symlinked evidence artifact")
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
                    raise ValueError("Concurrent artifact differs from expected bytes") from None
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    # One receipt per identical artifact. Historical release metadata belongs
    # to a separate versioned discovery manifest, not an overwritten receipt.
    receipt_path = folder / (digest + ".receipt.json")
    if receipt_path.is_symlink():
        raise ValueError("Symlinked source receipt")
    if not receipt_path.exists():
        fd, tmp = tempfile.mkstemp(dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(json.dumps(asdict(receipt), sort_keys=True, indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
            # Another writer may publish first; validate its complete receipt below.
            with suppress(FileExistsError):
                os.link(tmp, receipt_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    try:
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Invalid stored receipt") from exc
    if (not isinstance(existing, dict) or existing.get("source_id") != source_id
            or existing.get("sha256") != digest or existing.get("byte_count") != len(data)):
        raise ValueError("Stored receipt conflicts with source bytes")
    return receipt


def fetch_artifact(url: str, *, allowed_hosts: set[str], timeout: float = 30,
                   max_bytes: int = MAX_BYTES) -> tuple[bytes, str]:
    """Fetch over pinned-IP HTTPS without HTTP proxies or automatic redirects."""
    validate_url(url, allowed_hosts)
    parsed = urlparse(url)
    addresses = reject_nonpublic_dns(parsed.hostname)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    conn = _PinnedHTTPSConnection(parsed.hostname, addresses[0], timeout)
    try:
        conn.request("GET", path, headers={"Host": parsed.hostname,
                     "User-Agent": "AguaYLuz-HydroEvidence/1.0",
                     "Accept-Encoding": "identity"})
        response = conn.getresponse()
        if 300 <= response.status < 400:
            raise ValueError(f"Unexpected source HTTP status: {response.status}")
        if response.status != 200:
            raise HTTPError(url, response.status, "Source HTTP failure", None, None)
        content_length = response.getheader("Content-Length")
        if content_length is not None and int(content_length) > max_bytes:
            raise ValueError("Source payload exceeds size limit")
        data = response.read(max_bytes + 1)
        if not data or len(data) > max_bytes:
            raise ValueError("Source response empty or oversized")
        suffix = parsed.path.lower()
        if suffix.endswith((".xlsx", ".zip")) and not data.startswith(b"PK"):
            raise ValueError("Expected ZIP/OOXML bytes, received another format")
        if suffix.endswith(".pdf") and not data.startswith(b"%PDF-"):
            raise ValueError("Expected PDF bytes, received another format")
        return data, response.getheader("Content-Type", "application/octet-stream")
    finally:
        conn.close()


def acquire(root: Path, source_id: str, url: str, *,
            allowed_hosts: set[str], timeout: float = 30) -> ArtifactReceipt:
    try:
        raw, content_type = fetch_artifact(url, allowed_hosts=allowed_hosts, timeout=timeout)
        return persist_bytes(root, source_id, url, raw, content_type)
    except Exception:
        # A failed acquisition is NEVER a zero-generation observation.
        # Failure classification/retry policy is owned by the scheduler.
        raise
