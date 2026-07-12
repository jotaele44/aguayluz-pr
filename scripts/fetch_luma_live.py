#!/usr/bin/env python3
"""Fetch LIVE per-municipality outages from the MiLUMA API -> outages_by_town.json.

Pulls the same feed the (now-inactive) SuperSonicHub1/luma-energy-outages mirror
scraped, directly from LUMA's public outage API, and writes the
``{MUNICIPIO: [{zone, area}]}`` shape that scripts/ingest_aee.py consumes — giving
aguayluz a *live* per-municipio electric-outage source (the legacy AEEIncidents
SOAP feed and that mirror are both defunct).

ToS / ACCESS NOTE (read before scheduling this):
    api.miluma.lumapr.com sits behind an Incapsula WAF — plain clients get HTTP 403;
    a browser User-Agent + Referer is required. LUMA added that WAF (~2025-03, which
    killed the mirror) and has asked third parties to stop republishing its data.
    This fetcher is for LOW-FREQUENCY, INTERNAL monitoring by the aguayluz node, not
    republication. Poll sparingly; prefer an official LUMA / PR Energy Bureau
    data-sharing arrangement. Emitted events are tagged T2/needs_review accordingly.

Endpoints (from the mirror's .github/workflows/scrape.yml):
    POST /miluma-outage-api/outage/municipality/towns   body=["SAN JUAN", ...] -> per-town zones
    GET  /miluma-outage-api/outage/regionsWithoutService                       -> 7-region counts

Chains with the adapter (the printed command wires the snapshot timestamp + source):
    python scripts/fetch_luma_live.py --out /tmp/outages_by_town.json
    python scripts/ingest_aee.py --src /tmp/outages_by_town.json --snapshot-ts <ts> \\
        --source-ref '<ref>' --out data/aee_incidents.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Distinct exit code so callers (refresh.py --all treats this step as optional) and
# humans can tell a WAF/403/network block apart from a real crash (bug / bad geo file).
EXIT_SOURCE_UNAVAILABLE = 2


class SourceUnavailable(Exception):
    """The MiLUMA feed could not be reached (Incapsula WAF 403 or a network error).

    This is an expected, non-fatal condition — the endpoint is ToS/WAF-gated — not a
    bug in the adapter. ``main`` turns it into a typed one-line message + a dedicated
    exit code instead of letting a raw traceback escape.
    """

API = "https://api.miluma.lumapr.com/miluma-outage-api"
TOWNS_URL = f"{API}/outage/municipality/towns"
DEFAULT_GEO = "data/geo/pr_municipios.json"
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Referer": "https://miluma.lumapr.com/",
    "Accept": "application/json",
}


def municipio_keys(geo_path: Path) -> list[str]:
    """The 78 canonical municipios as the ALLCAPS/unaccented keys the API expects."""
    doc = json.loads(geo_path.read_text(encoding="utf-8"))
    keys = []
    for m in doc["municipios"]:
        folded = unicodedata.normalize("NFKD", m["name"]).encode("ascii", "ignore").decode()
        keys.append(" ".join(folded.upper().split()))
    return keys


def fetch_towns(municipios: list[str], timeout: float) -> dict:
    body = json.dumps(municipios).encode()
    req = urllib.request.Request(
        TOWNS_URL, data=body, method="POST",
        headers={**BROWSER_HEADERS, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https only)
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:  # 403 = Incapsula WAF block (the expected case)
        hint = " (Incapsula WAF block — needs a permissioned LUMA/PREB data path)" if exc.code == 403 else ""
        raise SourceUnavailable(f"HTTP {exc.code} from MiLUMA{hint}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:  # DNS / TLS / conn refused / timeout
        # A read-phase socket timeout raises TimeoutError directly (urllib only wraps
        # connect-phase OSErrors in URLError), so catch both to keep the no-traceback
        # source-unavailable contract on a slow/hung MiLUMA response.
        reason = getattr(exc, "reason", None) or "connection timed out"
        raise SourceUnavailable(f"cannot reach MiLUMA: {reason}") from exc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo", default=DEFAULT_GEO)
    ap.add_argument("--out", default="/tmp/outages_by_town.json")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    try:
        towns = fetch_towns(municipio_keys(Path(args.geo)), args.timeout)
    except SourceUnavailable as exc:
        # Expected, non-fatal: emit a typed one-liner (no traceback) and a dedicated
        # exit code so refresh.py --all can warn-and-continue on this optional step.
        print(f"source-unavailable: {exc}", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(towns, ensure_ascii=False, indent=2), encoding="utf-8")

    affected = {k: v for k, v in towns.items() if v}
    zones = sum(len(v) for v in towns.values())
    print(f"wrote {len(towns)} municipios ({zones} zone outages across {len(affected)} municipios) -> {out}")
    print(f"snapshot-ts: {ts}")
    print(f"source-ref:  {TOWNS_URL}  (live, fetched {ts})")
    print(f"next: python scripts/ingest_aee.py --src {out} --snapshot-ts {ts} "
          f"--source-ref '{TOWNS_URL}' --out data/aee_incidents.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
