#!/usr/bin/env python3
"""Fetch live MiLUMA outage manifestations for AguaYLuz.

The existing municipality/zone path remains the canonical detailed outage adapter:

    POST /miluma-outage-api/outage/municipality/towns

Optionally, callers may also request the separate regional-status manifestation:

    GET /miluma-outage-api/outage/regionsWithoutService

The two payloads are deliberately kept separate. Regional aggregates are not expanded
into municipality or zone events.

MiLUMA is protected by an Incapsula WAF. A browser-like User-Agent + Referer may still
receive HTTP 403. That is SOURCE_UNAVAILABLE, not a zero-outage observation.

Examples:
    python scripts/fetch_luma_live.py --out /tmp/outages_by_town.json
    python scripts/fetch_luma_live.py --out /tmp/outages_by_town.json \
        --status-out /tmp/luma_regions_without_service.json
"""
from __future__ import annotations

import argparse
import contextlib
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
    "Referer": "https://miluma.lumapr.com/",
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


def _request_json(req: urllib.request.Request, timeout: float) -> object:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read())
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


def fetch_towns(municipios: list[str], timeout: float) -> dict:
    body = json.dumps(municipios).encode()
    req = urllib.request.Request(
        TOWNS_URL,
        data=body,
        method="POST",
        headers={**BROWSER_HEADERS, "Content-Type": "application/json"},
    )
    result = _request_json(req, timeout)
    if not isinstance(result, dict):
        raise SourceUnavailable(
            f"unexpected municipality payload type: {type(result).__name__}"
        )
    return result


def fetch_regions(timeout: float) -> object:
    """Fetch the regional status payload without imposing an unverified schema."""
    req = urllib.request.Request(REGIONS_URL, method="GET", headers=BROWSER_HEADERS)
    return _request_json(req, timeout)


def _remove_stale_outputs(paths: list[Path]) -> None:
    """Fail closed: an unavailable live source must not leave old temp bytes reusable."""
    for path in paths:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo", default=DEFAULT_GEO)
    ap.add_argument("--out", default="/tmp/outages_by_town.json")
    ap.add_argument(
        "--status-out",
        default=None,
        help="optional raw regionsWithoutService JSON output; no regional→municipio inference",
    )
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    out = Path(args.out)
    status_out = Path(args.status_out) if args.status_out else None
    outputs = [out] + ([status_out] if status_out is not None else [])
    _remove_stale_outputs(outputs)

    try:
        towns = fetch_towns(municipio_keys(Path(args.geo)), args.timeout)
        regions = fetch_regions(args.timeout) if status_out is not None else None
    except SourceUnavailable as exc:
        _remove_stale_outputs(outputs)
        print(f"source-unavailable: {exc}", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(towns, ensure_ascii=False, indent=2), encoding="utf-8")

    affected = {k: v for k, v in towns.items() if v}
    zones = sum(len(v) for v in towns.values() if isinstance(v, list))
    print(
        f"wrote {len(towns)} municipios "
        f"({zones} zone outages across {len(affected)} municipios) -> {out}"
    )
    print(f"snapshot-ts: {ts}")
    print(f"source-ref:  {TOWNS_URL}  (live, fetched {ts})")

    if status_out is not None:
        status_out.parent.mkdir(parents=True, exist_ok=True)
        status_out.write_text(
            json.dumps(regions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"wrote regional status manifestation -> {status_out}")
        print(f"status-source-ref: {REGIONS_URL}  (live, fetched {ts})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
