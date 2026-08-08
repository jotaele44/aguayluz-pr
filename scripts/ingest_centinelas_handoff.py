#!/usr/bin/env python3
"""Durably ingest one idempotent Centinelas handoff envelope, then promote it.

Supported envelope kinds:
- environmental_signal (default/backward compatible) -> service_events.jsonl
- access_condition -> access_conditions.jsonl

Receipts remain content-addressed by idempotency_key. Duplicate deliveries are
acknowledged without re-promoting. Access conditions preserve T1 evidence and
cannot carry geometry; exact geometry binding is registry-controlled downstream.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_centinelas_access_condition import OUT_DEFAULT as ACCESS_OUT_DEFAULT  # noqa: E402
from ingest_centinelas_access_condition import promote_access_condition  # noqa: E402
from ingest_centinelas_dispatch import payload_to_event  # noqa: E402
from ingest_news_event import OUT_DEFAULT, _read_jsonl, _write_jsonl  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RECEIPTS_DEFAULT = REPO / "data" / "centinelas_handoffs"


def receipt_path(idempotency_key: str, receipts_dir: Path) -> Path:
    return receipts_dir / f"{hashlib.sha256(idempotency_key.encode()).hexdigest()}.json"


def write_receipt(payload: dict, receipts_dir: Path) -> tuple[Path, bool]:
    out = receipt_path(payload["idempotency_key"], receipts_dir)
    duplicate = out.exists()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not duplicate:
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out, duplicate


def promote_signal(
    payload: dict,
    events_out: Path,
    access_out: Path = ACCESS_OUT_DEFAULT,
) -> tuple[str | None, str | None]:
    signal = payload.get("signal")
    if not isinstance(signal, dict) or not signal:
        return None, None

    kind = payload.get("kind") or signal.get("kind") or "environmental_signal"
    if kind == "access_condition":
        row = promote_access_condition(signal, access_out)
        return None, row["condition_id"]
    if kind not in {"environmental_signal", "signal"}:
        raise ValueError(f"unsupported Centinelas handoff kind: {kind}")

    row = payload_to_event(signal)
    by_id = {e["event_id"]: e for e in _read_jsonl(events_out)}
    by_id[row["event_id"]] = row
    _write_jsonl(events_out, list(by_id.values()))
    return row["event_id"], None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipts-dir", default=str(RECEIPTS_DEFAULT))
    ap.add_argument("--events-out", default=str(OUT_DEFAULT))
    ap.add_argument("--access-out", default=str(ACCESS_OUT_DEFAULT))
    args = ap.parse_args()

    payload = json.loads(os.environ["CENTINELAS_CLIENT_PAYLOAD"])
    if payload["target"] != os.environ["EXPECTED_TARGET"]:
        raise SystemExit("handoff target mismatch")

    out, duplicate = write_receipt(payload, Path(args.receipts_dir))
    promoted_event = None
    promoted_condition = None
    if not duplicate:
        promoted_event, promoted_condition = promote_signal(
            payload, Path(args.events_out), Path(args.access_out)
        )

    print(f"receipt {'exists' if duplicate else 'written'}: {out}")
    if promoted_condition:
        print(f"promoted to access_conditions: {promoted_condition}")
    elif promoted_event:
        print(f"promoted to service_events: {promoted_event}")
    elif not duplicate:
        print("no `signal` in envelope — receipt stored, nothing to promote")

    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(
                f"duplicate={str(duplicate).lower()}\n"
                f"receipt_path={out}\n"
                f"promoted_event_id={promoted_event or ''}\n"
                f"promoted_condition_id={promoted_condition or ''}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
