#!/usr/bin/env python3
"""Build outputs/hub_packet.json (and a sidecar .sha256) for thehub-pr ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import OUTPUTS_DIR  # noqa: E402
from aguayluz.hub_packet import build_hub_packet, verify_packet_signature  # noqa: E402
from aguayluz.models import validate_against_schema  # noqa: E402


def _make_run_id(slug: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{slug}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the HubPacket for thehub-pr ingestion")
    p.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    p.add_argument("--run-id", default=None,
                   help="Run ID; defaults to YYYYMMDDTHHMMSSZ_hub-packet")
    args = p.parse_args(argv)

    run_id = args.run_id or _make_run_id("hub-packet")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    packet = build_hub_packet(
        outputs_dir=args.outputs_dir,
        run_id=run_id,
        generated_at=now_iso,
    )
    validate_against_schema("hub_packet", packet)

    if not verify_packet_signature(packet):
        print("export_hub_packet: signature self-check failed", file=sys.stderr)
        return 2

    (args.outputs_dir / "hub_packet.json").write_text(
        json.dumps(packet, indent=2), encoding="utf-8"
    )
    (args.outputs_dir / "hub_packet.sha256").write_text(
        packet["signature_sha256"] + "  hub_packet.json\n", encoding="utf-8"
    )

    print(
        f"signature={packet['signature_sha256'][:16]}… "
        f"assets={len(packet['entities']['utility_assets'])} "
        f"events={len(packet['entities']['service_events'])} "
        f"handoffs={len(packet['handoffs'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
