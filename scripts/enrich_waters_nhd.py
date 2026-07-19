#!/usr/bin/env python3
"""Enrich water assets with NHDPlus ids (comid/reachcode/vpuid) via EPA WATERS.

The ``src/aguayluz/waters/`` client (point-indexing against api.epa.gov/waters) is
fully implemented and tested but no ingest wired it in, so committed water assets
carry no NHDPlus identifiers. This pass point-indexes water assets that have coords
but no ``comid`` and writes the snapped reach ids back onto the asset rows; the
exporter already emits ``comid/reachcode/vpuid`` as ``external_ids`` when present,
so enriched assets become spatially joinable to other NHDPlus-aware producers.

Network + key gated, offline-safe by design: WATERS needs an api.data.gov key
(``EPA_WATERS_API_KEY`` / ``API_DATA_GOV_KEY``). With no key or no network the pass
prints a typed ``source-unavailable`` line and exits ``EXIT_SOURCE_UNAVAILABLE``
without modifying data — mirroring ``scripts/fetch_luma_live.py`` so ``refresh.py``
can treat it as optional. The downstream-contamination cascade (owld_locator) is a
noted follow-up, not wired here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz.waters import AuthError, WatersClient, WatersError  # noqa: E402
from aguayluz.waters.endpoints import first_flowline, point_indexing  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
EXIT_SOURCE_UNAVAILABLE = 2


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _needs_enrichment(a: dict[str, Any]) -> bool:
    return (
        a.get("asset_type") in ("water", "wastewater")
        and a.get("comid") is None
        and isinstance(a.get("lat"), (int, float))
        and isinstance(a.get("lon"), (int, float))
    )


def enrich_asset(client: WatersClient, asset: dict[str, Any]) -> bool:
    """Point-index one asset and write comid/reachcode/vpuid back. True if enriched."""
    resp = point_indexing(client, lon=float(asset["lon"]), lat=float(asset["lat"]))
    fl = first_flowline(resp)
    if not fl or fl.get("comid") is None:
        return False
    asset["comid"] = int(fl["comid"])
    if fl.get("reachcode") is not None:
        asset["reachcode"] = str(fl["reachcode"])
    if fl.get("nhdplus_region") is not None:
        asset["vpuid"] = fl["nhdplus_region"]
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", default="data/utility_assets.jsonl")
    ap.add_argument("--limit", type=int, default=50,
                    help="max assets to enrich per run (rate-budget); 0 = no cap")
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args()

    path = REPO_ROOT / args.assets
    assets = _read_jsonl(path)
    todo = [a for a in assets if _needs_enrichment(a)]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("no water assets need NHDPlus enrichment — nothing to do")
        return 0

    enriched = 0
    try:
        with WatersClient(api_key=args.api_key) as client:
            for a in todo:
                try:
                    if enrich_asset(client, a):
                        enriched += 1
                except WatersError as exc:
                    print(f"  skip {a.get('asset_id')}: {exc}", file=sys.stderr)
    except AuthError as exc:
        print(f"source-unavailable: WATERS key missing ({exc})", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE
    except WatersError as exc:
        print(f"source-unavailable: WATERS request failed ({exc})", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE

    if enriched:
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in assets))
    print(f"enriched {enriched}/{len(todo)} water assets with NHDPlus ids -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
