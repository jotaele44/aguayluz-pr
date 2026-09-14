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
    args = parser.parse_args()

    previous = load_snapshot(args.previous) if args.previous and args.previous.exists() else []
    current = fetch_current_records()
    freeze_snapshot(current, args.output)
    events = diff_records(previous, current)

    serialized_events = [asdict(event) for event in events]
    if args.events:
        args.events.parent.mkdir(parents=True, exist_ok=True)
        args.events.write_text(json.dumps(serialized_events, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        print(json.dumps(serialized_events, indent=2, ensure_ascii=False))

    approvals = [event for event in events if event.event_type == "DESLINDE_APPROVED"]
    print(f"records={len(current)} events={len(events)} approvals={len(approvals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
