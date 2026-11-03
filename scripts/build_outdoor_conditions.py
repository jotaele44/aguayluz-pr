#!/usr/bin/env python3
"""Compose the per-municipio outdoor-conditions layer → data/outdoor_conditions.jsonl.

Reads the outdoor state files, the hydromet plane, NWPS gauge state, Stage IV rainfall,
service events (NWS land alerts, NHC storms, USGS quakes), DRNA beach records and El
Yunque access conditions when present, and writes one row per municipio validated
against ``schemas/outdoor_condition.v1.schema.json`` (see
:mod:`aguayluz.outdoor.compose`). The federation export carries these rows to the hub as
``outdoor_condition`` entities.

Offline and network-free. A row keeps its ``composed_at`` until its content changes, and
the file is left untouched when no row changed, so a quiet 15-minute refresh commits
nothing and a buoy update rewrites only the coastal rows it touches.

Usage:
    python scripts/build_outdoor_conditions.py
    python scripts/build_outdoor_conditions.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import DATA_DIR  # noqa: E402
from aguayluz.hydromet import store  # noqa: E402
from aguayluz.models import validate_against_schema  # noqa: E402
from aguayluz.outdoor import conditions_path  # noqa: E402
from aguayluz.outdoor.compose import compose, load_inputs  # noqa: E402

SCHEMA = "outdoor_condition.v1"


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return datetime.now(timezone.utc).replace(microsecond=0)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _without_clock(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in row.items() if k != "composed_at"} for row in rows]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--reference", type=Path, default=None)
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--now", help="override the clock (ISO 8601), for reproducible tests")
    ap.add_argument("--dry-run", action="store_true", help="compose and validate; write nothing")
    args = ap.parse_args(argv)

    now = _parse_now(args.now)
    if now is None:
        print("--now is not a valid ISO 8601 timestamp", file=sys.stderr)
        return 2
    inputs = load_inputs(args.data_dir, reference_path=args.reference, registry_path=args.registry)
    rows = compose(inputs, now)
    for row in rows:
        try:
            validate_against_schema(SCHEMA, row)
        except Exception as exc:  # noqa: BLE001 - report which row, fail closed
            print(f"build_outdoor_conditions: {row['geoid']} fails {SCHEMA}: {exc}", file=sys.stderr)
            return 1

    levels = Counter(r["summary"]["level"] for r in rows)
    states = Counter((name, c["state"]) for r in rows for name, c in r["components"].items())
    carried = sum(1 for r in rows for c in r["components"].values() if c.get("carried_forward"))
    print(f"outdoor conditions: {len(rows)} municipios; levels {dict(sorted(levels.items()))}; "
          f"{carried} carried-forward component(s)")
    for name in sorted({n for n, _ in states}):
        print(f"  {name:20s} " + ", ".join(f"{s}={n}" for (c, s), n in sorted(states.items()) if c == name))
    if args.dry_run:
        return 0

    path = conditions_path(args.data_dir)
    previous = {r.get("geoid"): r for r in store.read_jsonl(path)} if path.is_file() else {}
    changed = 0
    for i, row in enumerate(rows):
        prior = previous.get(row["geoid"])
        # A row keeps its composed_at until its content changes, so a buoy update
        # rewrites the coastal rows it touches and nothing else.
        if prior is not None and _without_clock([prior]) == _without_clock([row]):
            rows[i] = {**row, "composed_at": prior["composed_at"]}
        else:
            changed += 1
    if not changed and len(previous) == len(rows):
        print(f"unchanged: {path}")
        return 0
    store.write_jsonl(path, rows)
    print(f"wrote {len(rows)} row(s), {changed} changed -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
