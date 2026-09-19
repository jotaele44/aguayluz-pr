#!/usr/bin/env python3
"""Fetch live MiLUMA outage manifestations with byte-level provenance.

Known public outage surfaces:
  POST /miluma-outage-api/outage/municipality/towns
  GET  /miluma-outage-api/outage/regionsWithoutService

The municipality feed is the detailed operational source. The regional feed is a
separate aggregate manifestation and is attempted independently. A regional WAF
failure must not discard a valid municipality snapshot.

Exact response bytes are written unchanged and a receipt binds endpoint, method,
retrieval UTC, byte count, and SHA-256. Source failure is never interpreted as zero
outages. Existing temp outputs are removed before each attempt so stale bytes cannot
silently pass downstream as current observations.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EXIT_SOURCE_UNAVAILABLE = 2


class SourceUnavailable(Exception):
    """The MiLUMA feed could not be reached."""


API = "https://api.miluma.lumapr.com/miluma-outage-api"
TOWNS_URL = f"{API}/outage/municipality/towns"
REGIONS_URL = f"{API}/outage/regionsWithoutService"
DEFAULT_GEO = "data/geo/pr_municipios.json"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://miluma.lumapr.com/view-outage-map",
    "Accept": "application/json",
}


def municipio_keys(geo_path: Path) -> list[str]:
    """Return the 78 canonical municipios as ALLCAPS/unaccented API keys."""
    doc = json.loads(geo_path.read_text(encoding="utf-8"))
    keys = []
    for m in doc["municipios"]:
        folded = unicodedata.normalize("NFKD", m["name"]).encode("ascii", "ignore").decode()
        keys.append(" ".join(folded.upper().split()))
    return keys


def _request_json(
    req: urllib.request.Request,
    timeout: float,
) -> tuple[object, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        hint = (
            " (Incapsula WAF block — needs a permissioned LUMA/PREB data path)"
            if exc.code == 403
            else ""
        )
        raise SourceUnavailable(f"HTTP {exc.code} from MiLUMA{hint}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", None) or "connection timed out"
        raise SourceUnavailable(f"cannot reach MiLUMA: {reason}") from exc

    try:
        return json.loads(raw), raw
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceUnavailable("MiLUMA returned invalid JSON") from exc


def fetch_towns(
    municipios: list[str],
    timeout: float,
) -> dict:
    body = json.dumps(municipios).encode()
    req = urllib.request.Request(
        TOWNS_URL,
        data=body,
        method="POST",
        headers={**BROWSER_HEADERS, "Content-Type": "application/json"},
    )
    result, _raw = _request_json(req, timeout)
    if not isinstance(result, dict):
        raise SourceUnavailable(
            f"unexpected municipality payload type: {type(result).__name__}"
        )
    return result


def fetch_regions(timeout: float) -> object:
    """Fetch regional status without imposing unverified field semantics."""
    req = urllib.request.Request(REGIONS_URL, method="GET", headers=BROWSER_HEADERS)
    result, _raw = _request_json(req, timeout)
    return result


def _remove_stale_outputs(paths: list[Path]) -> None:
    """Fail closed: unavailable live sources must not leave reusable stale bytes."""
    for path in paths:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--geo", default=DEFAULT_GEO)
    ap.add_argument("--out", default="/tmp/outages_by_town.json")
    ap.add_argument(
        "--status-out",
        default=None,
        help="optional exact regionsWithoutService response bytes",
    )
    ap.add_argument(
        "--manifest-out",
        default="/tmp/luma_snapshot_manifest.json",
        help="endpoint receipt manifest",
    )
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    out = Path(args.out)
    status_out = Path(args.status_out) if args.status_out else None
    manifest_out = Path(args.manifest_out)
    outputs = [out, manifest_out] + ([status_out] if status_out is not None else [])
    _remove_stale_outputs(outputs)
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)

    keys = municipio_keys(Path(args.geo))
    if len(keys) != 78 or len(set(keys)) != 78:
        print(
            f"source-invalid: municipio denominator expected 78 unique keys; "
            f"got rows={len(keys)} unique={len(set(keys))}",
            file=sys.stderr,
        )
        return 1

    body = json.dumps(keys).encode()
    town_req = urllib.request.Request(
        TOWNS_URL,
        data=body,
        method="POST",
        headers={**BROWSER_HEADERS, "Content-Type": "application/json"},
    )
    try:
        towns_obj, towns_raw = _request_json(town_req, args.timeout)
    except SourceUnavailable as exc:
        _remove_stale_outputs(outputs)
        print(f"source-unavailable: {exc}", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE
    if not isinstance(towns_obj, dict):
        _remove_stale_outputs(outputs)
        print(
            f"source-invalid: municipality payload type={type(towns_obj).__name__}",
            file=sys.stderr,
        )
        return 1

    towns_ts = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    out.write_bytes(towns_raw)
    manifest: dict[str, object] = {
        "schema_version": "miluma_live_snapshot_v1",
        "towns": {
            "status": "PASS",
            "method": "POST",
            "url": TOWNS_URL,
            "retrieval_utc": towns_ts,
            "response_bytes": len(towns_raw),
            "response_sha256": hashlib.sha256(towns_raw).hexdigest(),
            "request_key_count": len(keys),
            "request_body_sha256": hashlib.sha256(body).hexdigest(),
        },
        "regions": {
            "status": "NOT_REQUESTED",
            "method": "GET",
            "url": REGIONS_URL,
        },
    }

    if status_out is not None:
        region_req = urllib.request.Request(
            REGIONS_URL,
            method="GET",
            headers=BROWSER_HEADERS,
        )
        try:
            _regions_obj, regions_raw = _request_json(region_req, args.timeout)
        except SourceUnavailable as exc:
            manifest["regions"] = {
                "status": "SOURCE_UNAVAILABLE",
                "method": "GET",
                "url": REGIONS_URL,
                "error": str(exc),
            }
            with contextlib.suppress(FileNotFoundError):
                status_out.unlink()
            print(f"regional-source-unavailable: {exc}", file=sys.stderr)
        else:
            regions_ts = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            status_out.write_bytes(regions_raw)
            manifest["regions"] = {
                "status": "PASS",
                "method": "GET",
                "url": REGIONS_URL,
                "retrieval_utc": regions_ts,
                "response_bytes": len(regions_raw),
                "response_sha256": hashlib.sha256(regions_raw).hexdigest(),
            }
            print(f"wrote exact regional response bytes -> {status_out}")

    manifest_out.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    affected = {k: v for k, v in towns_obj.items() if v}
    zones = sum(len(v) for v in towns_obj.values() if isinstance(v, list))
    print(
        f"wrote exact town response bytes: {len(towns_obj)} keys "
        f"({zones} zone rows across {len(affected)} affected keys) -> {out}"
    )
    print(f"manifest: {manifest_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
