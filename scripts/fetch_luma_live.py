#!/usr/bin/env python3
"""Fetch the two known MiLUMA outage-map feeds with byte-level provenance.

The current MiLUMA outage surface is backed by two independently corroborated
endpoints:

* POST /miluma-outage-api/outage/municipality/towns
* GET  /miluma-outage-api/outage/regionsWithoutService

This fetcher preserves the exact response body bytes for each endpoint, validates
only the minimum source schema needed by downstream adapters, and writes a manifest
binding retrieval UTC, endpoint, request/response hashes, counts, and endpoint state.

MiLUMA is protected by an Incapsula WAF. A 403 or network failure is a source-access
state, not evidence that the source does not exist. The municipality feed is required
for this command to succeed. The regional feed is attempted independently and may be
recorded as SOURCE_UNAVAILABLE/SOURCE_INVALID without discarding a valid municipality
snapshot.

The output files are unlinked before network access. This prevents a failed fetch on
a persistent runner from leaving stale /tmp bytes that a downstream ingest could
mistake for a fresh observation.

Usage:
    python scripts/fetch_luma_live.py \
        --out /tmp/outages_by_town.json \
        --regions-out /tmp/luma_regions.json \
        --manifest-out /tmp/luma_snapshot_manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_SOURCE_UNAVAILABLE = 2
EXIT_SOURCE_INVALID = 3

API = "https://api.miluma.lumapr.com/miluma-outage-api"
TOWNS_URL = f"{API}/outage/municipality/towns"
REGIONS_URL = f"{API}/outage/regionsWithoutService"
DEFAULT_GEO = "data/geo/pr_municipios.json"
DEFAULT_OUT = "/tmp/outages_by_town.json"
DEFAULT_REGIONS_OUT = "/tmp/luma_regions.json"
DEFAULT_MANIFEST_OUT = "/tmp/luma_snapshot_manifest.json"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://miluma.lumapr.com/view-outage-map",
    "Accept": "application/json",
}


class SourceUnavailable(Exception):
    """MiLUMA could not be reached because of WAF/network/HTTP access state."""


class SourceInvalid(Exception):
    """MiLUMA responded, but the payload could not satisfy the minimum source schema."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def municipio_keys(geo_path: Path) -> list[str]:
    """Return the 78 canonical municipios as ALLCAPS/unaccented API request keys."""
    doc = json.loads(geo_path.read_text(encoding="utf-8"))
    keys = []
    for m in doc["municipios"]:
        folded = unicodedata.normalize("NFKD", m["name"]).encode("ascii", "ignore").decode()
        keys.append(" ".join(folded.upper().split()))
    return keys


def _request_json(req: urllib.request.Request, timeout: float, label: str) -> tuple[Any, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https only)
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        hint = (
            " (Incapsula WAF block — needs a permissioned LUMA/PREB data path)"
            if exc.code == 403
            else ""
        )
        raise SourceUnavailable(f"HTTP {exc.code} from MiLUMA {label}{hint}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", None) or "connection timed out"
        raise SourceUnavailable(f"cannot reach MiLUMA {label}: {reason}") from exc

    try:
        return json.loads(raw), raw
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceInvalid(f"MiLUMA {label} returned non-JSON/invalid JSON") from exc


def _towns_body(municipios: list[str]) -> bytes:
    return json.dumps(municipios, separators=(",", ":")).encode()


def _validate_towns(doc: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(doc, dict):
        raise SourceInvalid("MiLUMA towns payload is not an object")
    for raw_muni, rows in doc.items():
        if not isinstance(raw_muni, str) or not isinstance(rows, list):
            raise SourceInvalid("MiLUMA towns payload has a non-string key or non-list value")
        for row in rows:
            if not isinstance(row, dict):
                raise SourceInvalid(f"MiLUMA towns row for {raw_muni!r} is not an object")
            area = row.get("area")
            zone = row.get("zone")
            if not isinstance(area, str) or not area.strip():
                raise SourceInvalid(f"MiLUMA towns row for {raw_muni!r} lacks a valid area")
            if zone is not None and not isinstance(zone, str):
                raise SourceInvalid(f"MiLUMA towns row for {raw_muni!r} has non-string zone")
    return doc


def _validate_regions(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict) or not isinstance(doc.get("regions"), list):
        raise SourceInvalid("MiLUMA regions payload lacks a regions list")

    seen: set[str] = set()
    for row in doc["regions"]:
        if not isinstance(row, dict):
            raise SourceInvalid("MiLUMA regions row is not an object")
        name = row.get("name")
        total = row.get("totalClients")
        affected = row.get("totalClientsWithoutService")
        if not isinstance(name, str) or not name.strip():
            raise SourceInvalid("MiLUMA regions row lacks a valid name")
        if name in seen:
            raise SourceInvalid(f"MiLUMA regions payload repeats region {name!r}")
        seen.add(name)
        for field, value in (("totalClients", total), ("totalClientsWithoutService", affected)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SourceInvalid(f"MiLUMA region {name!r} has non-numeric {field}")
            if value < 0 or int(value) != value:
                raise SourceInvalid(f"MiLUMA region {name!r} has invalid {field}={value!r}")
        if affected > total:
            raise SourceInvalid(
                f"MiLUMA region {name!r} has affected customers greater than total customers"
            )
    return doc


def fetch_towns_snapshot(
    municipios: list[str], timeout: float
) -> tuple[dict[str, list[dict[str, Any]]], bytes]:
    body = _towns_body(municipios)
    req = urllib.request.Request(
        TOWNS_URL,
        data=body,
        method="POST",
        headers={**BROWSER_HEADERS, "Content-Type": "application/json"},
    )
    doc, raw = _request_json(req, timeout, "municipality/towns")
    return _validate_towns(doc), raw


def fetch_towns(municipios: list[str], timeout: float) -> dict[str, list[dict[str, Any]]]:
    """Compatibility wrapper returning only the parsed municipality payload."""
    doc, _raw = fetch_towns_snapshot(municipios, timeout)
    return doc


def fetch_regions_snapshot(timeout: float) -> tuple[dict[str, Any], bytes]:
    req = urllib.request.Request(REGIONS_URL, method="GET", headers=BROWSER_HEADERS)
    doc, raw = _request_json(req, timeout, "regionsWithoutService")
    return _validate_regions(doc), raw


def fetch_regions(timeout: float) -> dict[str, Any]:
    """Compatibility wrapper returning only the parsed regional payload."""
    doc, _raw = fetch_regions_snapshot(timeout)
    return doc


def _town_stats(doc: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    tuples = [
        (raw_muni, str(row.get("area", "")), str(row.get("zone", "")))
        for raw_muni, rows in doc.items()
        for row in rows
    ]
    return {
        "top_level_key_count": len(doc),
        "zone_row_count": len(tuples),
        "duplicate_zone_row_count": len(tuples) - len(set(tuples)),
    }


def _region_stats(doc: dict[str, Any]) -> dict[str, int]:
    rows = doc["regions"]
    return {
        "region_row_count": len(rows),
        "total_customers_sum": sum(int(row["totalClients"]) for row in rows),
        "affected_customers_sum": sum(int(row["totalClientsWithoutService"]) for row in rows),
    }


def _endpoint_entry(
    *,
    status: str,
    method: str,
    url: str,
    retrieval_utc: str | None = None,
    response_raw: bytes | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"status": status, "method": method, "url": url}
    if retrieval_utc:
        entry["retrieval_utc"] = retrieval_utc
    if response_raw is not None:
        entry["response_sha256"] = _sha256(response_raw)
        entry["response_bytes"] = len(response_raw)
    if error:
        entry["error"] = error
    if extra:
        entry.update(extra)
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo", default=DEFAULT_GEO)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--regions-out", default=DEFAULT_REGIONS_OUT)
    ap.add_argument("--manifest-out", default=DEFAULT_MANIFEST_OUT)
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    out = Path(args.out)
    regions_out = Path(args.regions_out)
    manifest_out = Path(args.manifest_out)
    for path in (out, regions_out, manifest_out):
        path.unlink(missing_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)

    keys = municipio_keys(Path(args.geo))
    try:
        towns, towns_raw = fetch_towns_snapshot(keys, args.timeout)
    except SourceUnavailable as exc:
        print(f"source-unavailable: {exc}", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE
    except SourceInvalid as exc:
        print(f"source-invalid: {exc}", file=sys.stderr)
        return EXIT_SOURCE_INVALID

    towns_ts = _utc_now()
    out.write_bytes(towns_raw)
    towns_entry = _endpoint_entry(
        status="PASS",
        method="POST",
        url=TOWNS_URL,
        retrieval_utc=towns_ts,
        response_raw=towns_raw,
        extra={
            "request_key_count": len(keys),
            "request_body_sha256": _sha256(_towns_body(keys)),
            **_town_stats(towns),
        },
    )

    try:
        regions, regions_raw = fetch_regions_snapshot(args.timeout)
    except SourceUnavailable as exc:
        regions_entry = _endpoint_entry(
            status="SOURCE_UNAVAILABLE", method="GET", url=REGIONS_URL, error=str(exc)
        )
        print(f"regional-source-unavailable: {exc}", file=sys.stderr)
    except SourceInvalid as exc:
        regions_entry = _endpoint_entry(
            status="SOURCE_INVALID", method="GET", url=REGIONS_URL, error=str(exc)
        )
        print(f"regional-source-invalid: {exc}", file=sys.stderr)
    else:
        regions_ts = _utc_now()
        regions_out.write_bytes(regions_raw)
        regions_entry = _endpoint_entry(
            status="PASS",
            method="GET",
            url=REGIONS_URL,
            retrieval_utc=regions_ts,
            response_raw=regions_raw,
            extra=_region_stats(regions),
        )

    manifest = {
        "schema_version": "miluma_live_snapshot_v1",
        "towns": towns_entry,
        "regions": regions_entry,
    }
    manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    affected = {k: v for k, v in towns.items() if v}
    zones = sum(len(v) for v in towns.values())
    print(
        f"wrote exact MiLUMA towns body: {len(towns)} keys, "
        f"{zones} zone rows across {len(affected)} affected keys -> {out}"
    )
    if regions_entry["status"] == "PASS":
        print(
            f"wrote exact MiLUMA regional body: {regions_entry['region_row_count']} regions -> "
            f"{regions_out}"
        )
    print(f"manifest: {manifest_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
