"""Classify verified source-byte manifestations; no network access or promotion.

Inputs must be independently frozen original-byte receipts. This module compares
claims in records; it does not certify receipt-to-byte integrity on its own.
"""
from __future__ import annotations

import re

from .acquisition import validate_url

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def classify_manifestations(
    existing: list[dict], incoming: list[dict], *,
    allowed_hosts: dict[str, set[str]],
) -> list[dict]:
    """Classify manifestations without collapsing URLs, revisions or sources."""
    if not isinstance(existing, list) or not isinstance(incoming, list):
        raise ValueError("Manifestation collections must be lists")

    def checked(record: dict) -> tuple[str, str, str]:
        if not isinstance(record, dict):
            raise ValueError("Invalid manifestation record")
        source = record.get("source_id")
        url = record.get("artifact_url")
        digest = record.get("sha256")
        if not isinstance(source, str) or source not in allowed_hosts:
            raise ValueError("Unknown manifestation source ID")
        if not isinstance(url, str):
            raise ValueError("Missing artifact URL")
        validate_url(url, allowed_hosts[source])
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError("Invalid original-byte SHA-256")
        return source, url, digest

    prior = [checked(row) for row in existing]
    current = [checked(row) for row in incoming]
    previous = set(prior)
    prior_by_url: dict[tuple[str, str], set[str]] = {}
    prior_by_hash: dict[tuple[str, str], set[str]] = {}
    current_by_url: dict[tuple[str, str], set[str]] = {}
    for source, url, digest in prior:
        prior_by_url.setdefault((source, url), set()).add(digest)
        prior_by_hash.setdefault((source, digest), set()).add(url)
    for source, url, digest in current:
        current_by_url.setdefault((source, url), set()).add(digest)

    out = []
    for source, url, digest in current:
        if len(current_by_url[(source, url)]) > 1:
            state = "REVIEW_CONFLICTING_CURRENT_URL"
        elif (source, url, digest) in previous:
            state = "BYTE_IDENTICAL_URL_REOBSERVED"
        elif (source, url) in prior_by_url:
            state = "SAME_URL_REVISED_BYTES"
        elif (source, digest) in prior_by_hash:
            state = "SAME_BYTES_NEW_URL"
        else:
            state = "NEW_URL_NEW_BYTES"
        out.append({
            "source_id": source,
            "artifact_url": url,
            "sha256": digest,
            "state": state,
            "acquisition_state": "NOT_ASSERTED_BY_CLASSIFIER",
            "canonical_promotion": False,
        })
    return out
