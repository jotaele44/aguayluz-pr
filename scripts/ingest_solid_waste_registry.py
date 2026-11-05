#!/usr/bin/env python3
"""Freeze and ingest the Puerto Rico solid-waste (vertedero/landfill) site registry.

Implements the registry proposed in ``docs/adr/ADR-0004-solid-waste-registry-ownership.md``.
It builds canonical site records from two public federal sources, keeps their RAW rows
apart, and records every cross-source match as a candidate that is never merged:

* **EPA LMOP** Landfill and Landfill Gas Energy Project Database (xlsx): the Puerto Rico rows.
  Tier T1. Carries precise coordinates, owner/operator, years opened/closed, open/closed status.
* **EPA ECHO** facility query with SIC code 4953 (refuse systems) for Puerto Rico. Tier T1.
  Fail-closed control: ECHO silently ignores unknown filters (``p_naics`` returns the whole
  state), so the filtered row count must be below the unfiltered count.

The result is always OPEN, never CERTIFIED: no structured Puerto Rico solid-waste authority
list, no EPA Region 2 enforcement records and no unauthorized-dump source have been acquired.

Run:
    python scripts/ingest_solid_waste_registry.py                    # live fetch, write data/
    python scripts/ingest_solid_waste_registry.py --dry-run          # build and print, write nothing
    python scripts/ingest_solid_waste_registry.py --lmop-src f.xlsx --echo-src echo.json   # offline

Writes ``data/environmental_entities.jsonl``, ``environmental_geometries.jsonl``,
``environmental_exposure_events.jsonl`` (via ``aguayluz.environmental_exposure_db``),
``data/solid_waste_source_rows.jsonl`` (RAW rows) and ``data/solid_waste_receipts.json``
(manifestations, candidate bindings, coverage ledger).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from aguayluz import DATA_DIR  # noqa: E402
from aguayluz import environmental_exposure_db as db  # noqa: E402
from aguayluz import solid_waste as sw  # noqa: E402

LMOP_URL = "https://www.epa.gov/system/files/documents/2024-09/landfilllmopdata.xlsx"
ECHO_BASE = "https://echodata.epa.gov/echo/echo_rest_services"
USER_AGENT = "aguayluz-pr/0.1 (github.com/jotaele44/aguayluz-pr)"
OWNED_AUTHORITIES = frozenset({sw.LMOP_AUTHORITY, sw.ECHO_AUTHORITY})
MAX_ECHO_PAGES = 50


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    from aguayluz.http_retry import get_with_retry

    response = get_with_retry(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=120)
    response.raise_for_status()
    return response


def fetch_lmop_bytes(url: str) -> bytes:
    return bytes(_get(url).content)


def fetch_echo() -> dict[str, Any]:
    """Two-step ECHO fetch (QueryID, then paged rows) plus the unfiltered control count."""
    base_params = {"output": "JSON", "p_st": sw.PR_STATE}
    filtered = _get(f"{ECHO_BASE}.get_facilities", {**base_params, "p_sic": sw.ECHO_SIC}).json()["Results"]
    unfiltered = _get(f"{ECHO_BASE}.get_facilities", base_params).json()["Results"]
    expected = int(filtered["QueryRows"])
    facilities: list[dict[str, Any]] = []
    for page in range(1, MAX_ECHO_PAGES + 1):
        result = _get(
            f"{ECHO_BASE}.get_qid",
            {"output": "JSON", "qid": filtered["QueryID"], "pageno": page, "qcolumns": sw.ECHO_QCOLUMNS},
        ).json()["Results"]
        rows = result.get("Facilities") or []
        facilities.extend(rows)
        if not rows or len(facilities) >= expected:
            break
    return {
        "query": {**base_params, "p_sic": sw.ECHO_SIC},
        "qcolumns": sw.ECHO_QCOLUMNS,
        "filtered_rows": expected,
        "unfiltered_rows": int(unfiltered["QueryRows"]),
        "facilities": facilities,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _usgs_landfill_wells(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        a
        for a in assets
        if str(a.get("asset_id", "")).startswith("USGSWQ_")
        and any(word in str(a.get("asset_name", "")).upper() for word in ("VERTEDERO", "LANDFILL"))
    ]


def build(
    lmop_bytes: bytes,
    lmop_url: str,
    echo: dict[str, Any],
    assets: list[dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    """Build every record and receipt in memory. Raises (and writes nothing) on any failed control."""
    release = sw.lmop_release_from_url(lmop_url)
    table = sw.read_lmop_workbook(lmop_bytes)
    pr_rows = sw.select_state(table.rows)
    lmop = sw.build_lmop_records(pr_rows, release)

    control = sw.echo_filter_control(int(echo["filtered_rows"]), int(echo["unfiltered_rows"]))
    facilities = list(echo["facilities"])
    if len(facilities) != int(echo["filtered_rows"]):
        raise ValueError(
            f"ECHO returned {len(facilities)} rows but the query reported {echo['filtered_rows']}"
        )
    label = f"p_sic={sw.ECHO_SIC}"
    echo_records = sw.build_echo_records(facilities, label)

    lmop_cands = sw.candidates_from_records(lmop)
    echo_cands = sw.candidates_from_records(echo_records)
    pins, wells = sw.seed_candidates(_usgs_landfill_wells(assets))
    same_echo, unbound_echo = sw.candidate_bindings(lmop_cands, echo_cands, "SAME_SITE_CANDIDATE")
    same_pin, unbound_pin = sw.candidate_bindings(lmop_cands, pins, "SAME_SITE_CANDIDATE")
    related_wells, unbound_wells = sw.candidate_bindings(
        lmop_cands, wells, "RELATED_MONITORING_LOCATION_CANDIDATE"
    )
    bindings = sorted(same_echo + same_pin + related_wells, key=lambda b: b["binding_id"])
    ledger = sw.coverage_ledger(
        lmop_total_rows=len(table.rows),
        lmop_pr_rows=len(pr_rows),
        lmop=lmop,
        echo_rows=len(facilities),
        echo=echo_records,
        bindings=bindings,
        unbound={"lmop_vs_echo": unbound_echo, "lmop_vs_pins": unbound_pin, "lmop_vs_wells": unbound_wells},
    )
    manifestations = [
        {
            "source_id": "EPA_LMOP",
            "authority": "U.S. EPA Landfill Methane Outreach Program",
            "title": "Landfill and Landfill Gas Energy Project Database",
            "locator": lmop_url,
            "release": release,
            "retrieved_at": now,
            "byte_sha256": hashlib.sha256(lmop_bytes).hexdigest(),
            "byte_count": len(lmop_bytes),
            "sheet": table.sheet,
            "header": list(table.headers),
            "total_rows": len(table.rows),
            "pr_rows": len(pr_rows),
            "evidence_tier": "T1",
        },
        {
            "source_id": "EPA_ECHO",
            "authority": "U.S. EPA Enforcement and Compliance History Online",
            "title": "ECHO facility query, Puerto Rico, SIC 4953 (refuse systems)",
            "locator": f"{ECHO_BASE}.get_facilities",
            "query": echo["query"],
            "qcolumns": echo.get("qcolumns", sw.ECHO_QCOLUMNS),
            "retrieved_at": now,
            "response_sha256": sw.canonical_sha256(facilities),
            "row_count": len(facilities),
            "filter_control": control,
            "evidence_tier": "T1",
        },
    ]
    notes = lmop.notes + echo_records.notes
    return {
        "lmop": lmop,
        "echo": echo_records,
        "receipts": sw.build_receipts(
            manifestations=manifestations, bindings=bindings, ledger=ledger, notes=notes, now=now
        ),
    }


def write_outputs(built: dict[str, Any], data_dir: Path) -> None:
    lmop, echo_records = built["lmop"], built["echo"]
    entities = lmop.entities + echo_records.entities
    geometries = lmop.geometries + echo_records.geometries
    events = lmop.events + echo_records.events
    paths = {
        "environmental_entity": data_dir / "environmental_entities.jsonl",
        "environmental_geometry": data_dir / "environmental_geometries.jsonl",
        "environmental_exposure_event": data_dir / "environmental_exposure_events.jsonl",
    }
    owned_ids = {
        e["entity_id"]
        for e in db.load("environmental_entity", paths["environmental_entity"])
        if e["authority"] in OWNED_AUTHORITIES
    } | {e["entity_id"] for e in entities}
    db.replace_where(
        "environmental_entity", entities,
        drop=lambda r: r["authority"] in OWNED_AUTHORITIES, path=paths["environmental_entity"],
    )
    db.replace_where(
        "environmental_geometry", geometries,
        drop=lambda r: r["entity_id"] in owned_ids, path=paths["environmental_geometry"],
    )
    db.replace_where(
        "environmental_exposure_event", events,
        drop=lambda r: bool(owned_ids & set(r["entity_ids"])), path=paths["environmental_exposure_event"],
    )
    raw_rows = sorted(lmop.raw_rows + echo_records.raw_rows, key=lambda r: r["source_record_id"])
    (data_dir / "solid_waste_source_rows.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in raw_rows),
        encoding="utf-8",
    )
    (data_dir / "solid_waste_receipts.json").write_text(
        json.dumps(built["receipts"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lmop-src", help="offline LMOP xlsx file (default: fetch --lmop-url)")
    ap.add_argument("--lmop-url", default=LMOP_URL, help="LMOP workbook URL; the release is read from it")
    ap.add_argument("--echo-src", help="offline ECHO JSON ({query, filtered_rows, unfiltered_rows, facilities})")
    ap.add_argument("--assets", default=str(DATA_DIR / "utility_assets.jsonl"))
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--retrieved-at", help="override the retrieval timestamp (reproducible runs)")
    ap.add_argument("--dry-run", action="store_true", help="build and print the ledger; write nothing")
    args = ap.parse_args(argv)

    now = args.retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    try:
        lmop_bytes = Path(args.lmop_src).read_bytes() if args.lmop_src else fetch_lmop_bytes(args.lmop_url)
        echo = json.loads(Path(args.echo_src).read_text(encoding="utf-8")) if args.echo_src else fetch_echo()
        built = build(lmop_bytes, args.lmop_url, echo, _load_jsonl(Path(args.assets)), now)
    except (sw.FilterIgnoredError, ValueError, KeyError) as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 2

    ledger = built["receipts"]["coverage_ledger"]
    print(json.dumps({"result": built["receipts"]["result"], "coverage_ledger": ledger}, indent=2, sort_keys=True))
    if args.dry_run:
        print("dry-run: nothing written")
        return 0
    write_outputs(built, Path(args.data_dir))
    print(f"wrote {Path(args.data_dir)} (entities, geometries, events, source rows, receipts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
