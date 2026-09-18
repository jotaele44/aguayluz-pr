#!/usr/bin/env python3
"""Acquire DRNA approved ZMT deslindes and diff against a prior frozen snapshot."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from aguayluz.drna_deslindes import diff_records, fetch_current_records, freeze_snapshot, load_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, help="Prior logical snapshot JSON")
    parser.add_argument("--output", type=Path, required=True, help="Destination for current snapshot")
    parser.add_argument("--events", type=Path, help="Optional JSON destination for transition events")
    parser.add_argument(
        "--raw-cas",
        type=Path,
        default=Path("data/drna_deslindes/raw_cas"),
        help="Content-addressed raw-byte store for listing/detail manifestations",
    )
    parser.add_argument(
        "--emit-bootstrap-approvals",
        action="store_true",
        help="Explicitly emit historical approvals on first acquisition; off by default",
    )
    args = parser.parse_args()

    has_previous = bool(args.previous and args.previous.exists())
    previous = load_snapshot(args.previous) if has_previous else []
    current = fetch_current_records(cas_dir=args.raw_cas)
    freeze_snapshot(current, args.output)

    # First acquisition establishes the baseline denominator. It must not masquerade
    # as a set of approvals that occurred during the monitoring interval.
    events = diff_records(previous, current) if has_previous or args.emit_bootstrap_approvals else []

    serialized_events = [asdict(event) for event in events]
    if args.events:
        args.events.parent.mkdir(parents=True, exist_ok=True)
        args.events.write_text(
            json.dumps(serialized_events, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        print(json.dumps(serialized_events, indent=2, ensure_ascii=False))

    approvals = [event for event in events if event.event_type == "DESLINDE_APPROVED"]
    mode = "DIFF" if has_previous else "BASELINE"
    print(
        f"mode={mode} records={len(current)} events={len(events)} "
        f"approvals={len(approvals)} raw_cas={args.raw_cas}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
