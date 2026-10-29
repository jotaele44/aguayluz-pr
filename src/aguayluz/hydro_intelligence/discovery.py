"""Source release discovery and fail-closed acquisition scheduling.

No canonical promotion: candidate discovery and acquisition results are evidence only.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request
from html.parser import HTMLParser

from .acquisition import fetch_artifact, persist_bytes, validate_url


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


@dataclass(frozen=True)
class DiscoveryCandidate:
    source_id: str
    index_url: str
    artifact_url: str
    observed_at: str
    state: str = "DISCOVERED_NOT_ACQUIRED"


def discover_links(source_id: str, index_url: str, html_bytes: bytes,
                   allowed_hosts: set[str], suffixes: tuple[str, ...]) -> list[DiscoveryCandidate]:
    validate_url(index_url, allowed_hosts)
    parser = _Links()
    parser.feed(html_bytes.decode("utf-8", errors="replace"))
    stamp = datetime.now(timezone.utc).isoformat()
    items = {}
    for href in parser.links:
        url = urljoin(index_url, href)
        try:
            validate_url(url, allowed_hosts)
        except ValueError:
            continue
        if urlparse(url).path.lower().endswith(suffixes):
            items[url] = DiscoveryCandidate(source_id, index_url, url, stamp)
    return [items[url] for url in sorted(items)]


def classify_failure(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if code in (401, 403):
        return "ACCESS_DENIED"
    if code == 404:
        return "NOT_FOUND_AT_URL"
    if code == 429 or (isinstance(code, int) and 500 <= code <= 599):
        return "RETRYABLE_HTTP"
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return "RETRYABLE_TRANSPORT"
    if isinstance(error, ValueError):
        return "INVALID_SOURCE_RESPONSE"
    return "UNCLASSIFIED_FAILURE"


def acquire_with_retry(root: Path, source_id: str, url: str, *,
                       allowed_hosts: set[str], attempts: int = 3,
                       base_delay: float = 1, sleeper=time.sleep, fetcher=fetch_artifact) -> dict:
    if attempts < 1 or attempts > 8:
        raise ValueError("attempts out of bounds")
    validate_url(url, allowed_hosts)
    failures = []
    for i in range(attempts):
        try:
            raw, media = fetcher(url, allowed_hosts=allowed_hosts)
            receipt = persist_bytes(root, source_id, url, raw, media)
            return {"state": "RAW_FROZEN_NOT_PARSED", "receipt": asdict(receipt),
                    "failed_attempts": failures}
        except Exception as error:
            category = classify_failure(error)
            failures.append({"attempt": i + 1, "category": category,
                             "exception_type": type(error).__name__})
            if category not in ("RETRYABLE_HTTP", "RETRYABLE_TRANSPORT") or i + 1 == attempts:
                break
            sleeper(min(30.0, base_delay * (2 ** i)))
    return {"state": "QUARANTINED_NOT_PROMOTED", "source_id": source_id,
            "url": url, "failures": failures}


def freeze_result_log(path: Path, results: list[dict]) -> str:
    """Write a new immutable run receipt; refuse an existing destination."""
    encoded = (json.dumps(results, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as out:
        out.write(encoded)
    return hashlib.sha256(encoded).hexdigest()
