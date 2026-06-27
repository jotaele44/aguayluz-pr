#!/usr/bin/env python3
"""Build the AguaYLuz-PR alert system from its DDL + seed data.

Creates a local SQLite database (default ``outputs/alert_system.sqlite``, which
is gitignored) from ``schemas/sql/alert_system.sql``, loads the module registry,
seed alert events, dependency edges, and gap log, runs the VAL-001..010
validation pipeline, and emits ``outputs/alert_events.geojson``.

Schema-validation happens during load (each row is checked against its JSON
Schema), so a malformed seed fails loudly here rather than at federation export.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import OUTPUTS_DIR  # noqa: E402
from aguayluz.alert_db import (  # noqa: E402
    build_sqlite,
    events_to_geojson,
    load_edges,
    load_events,
    load_gaps,
    load_modules,
)
from aguayluz.alert_validation import validate_alerts  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(OUTPUTS_DIR / "alert_system.sqlite"))
    ap.add_argument("--geojson", default=str(OUTPUTS_DIR / "alert_events.geojson"))
    ap.add_argument("--in-memory", action="store_true", help="build in memory; do not write the DB file")
    args = ap.parse_args()

    modules = load_modules()
    events = load_events()
    edges = load_edges()
    gaps = load_gaps()
    print(f"loaded {len(modules)} modules, {len(events)} events, {len(edges)} edges, {len(gaps)} gaps")

    db_target = ":memory:" if args.in_memory else args.db
    conn = build_sqlite(db_target, modules=modules, events=events, edges=edges, gaps=gaps)
    active = conn.execute(
        "SELECT count(*) FROM alert_modules WHERE activation_status='active'"
    ).fetchone()[0]
    conn.close()
    print(f"built SQLite ({db_target}); {active} active modules")

    results = validate_alerts(events)
    rejected = [r.as_dict() for r in results if not r.valid]
    advisories = sum(len(r.violations) for r in results) - sum(len(r.rejecting_violations) for r in results)
    print(f"VAL pipeline: {len(events) - len(rejected)}/{len(events)} accepted, "
          f"{len(rejected)} rejected, {advisories} advisory note(s)")
    if rejected:
        print(json.dumps(rejected, indent=2))

    geo = events_to_geojson(events)
    out = Path(args.geojson)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(geo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(geo['features'])} geo feature(s) -> {out}")

    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
