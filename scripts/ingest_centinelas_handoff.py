#!/usr/bin/env python3
"""Durably ingest one idempotent Centinelas handoff envelope, then promote it.

Two hops in one step, both idempotent:

1. **Receipt.** The envelope (``item_id`` / ``target`` / ``idempotency_key`` /
   ``signal``) is written to ``data/centinelas_handoffs/<sha256(key)>.json``. A
   redelivery of the same key is a no-op and reports ``duplicate=true``, which is
   what the acknowledgement hop reports back to centinelas-pr.
2. **Promotion.** The envelope's ``signal`` is the same intake record the
   ``centinelas-signal`` path carries, so it goes through
   ``ingest_centinelas_dispatch.payload_to_event`` into ``data/service_events.jsonl``
   (evidence tier T3, ``review_status=needs_review``), merged by ``event_id``.
   Without this a handoff was a dead end: the receipt was stored and acked, but the
   signal never reached the corpus the exporter and dashboard read.

Promotion is skipped for a duplicate receipt (that signal is already in the corpus)
and for an envelope carrying no ``signal``, which is reported rather than treated as
a failure.

Input: ``CENTINELAS_CLIENT_PAYLOAD`` (JSON) + ``EXPECTED_TARGET`` env vars, as posted
by ``.github/workflows/centinelas-handoff.yml``. Step outputs (``duplicate``,
``receipt_path``, ``promoted_event_id``) are appended to ``GITHUB_OUTPUT`` when set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_centinelas_dispatch import payload_to_event  # noqa: E402
from ingest_news_event import OUT_DEFAULT, _read_jsonl, _write_jsonl  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RECEIPTS_DEFAULT = REPO / "data" / "centinelas_handoffs"


def receipt_path(idempotency_key: str, receipts_dir: Path) -> Path:
    """Content-addressed receipt path — one key always resolves to one file."""
    return receipts_dir / f"{hashlib.sha256(idempotency_key.encode()).hexdigest()}.json"


def write_receipt(payload: dict, receipts_dir: Path) -> tuple[Path, bool]:
    """Persist the envelope. Returns (path, duplicate)."""
    out = receipt_path(payload["idempotency_key"], receipts_dir)
    duplicate = out.exists()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not duplicate:
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out, duplicate


def promote_signal(payload: dict, events_out: Path) -> str | None:
    """Merge the envelope's ``signal`` into service_events; returns the event_id.

    ``None`` when the envelope carries no signal to promote.
    """
    signal = payload.get("signal")
    if not isinstance(signal, dict) or not signal:
        return None
    row = payload_to_event(signal)
    by_id = {e["event_id"]: e for e in _read_jsonl(events_out)}
    by_id[row["event_id"]] = row
    _write_jsonl(events_out, list(by_id.values()))
    return row["event_id"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipts-dir", default=str(RECEIPTS_DEFAULT))
    ap.add_argument("--events-out", default=str(OUT_DEFAULT))
    args = ap.parse_args()

    payload = json.loads(os.environ["CENTINELAS_CLIENT_PAYLOAD"])
    if payload["target"] != os.environ["EXPECTED_TARGET"]:
        raise SystemExit("handoff target mismatch")

    out, duplicate = write_receipt(payload, Path(args.receipts_dir))
    # A duplicate delivery's signal is already in the corpus. Re-promoting would be
    # harmless (the merge is by event_id) but would dirty the tree on every redelivery.
    promoted = None if duplicate else promote_signal(payload, Path(args.events_out))

    print(f"receipt {'exists' if duplicate else 'written'}: {out}")
    if promoted:
        print(f"promoted to service_events: {promoted}")
    elif not duplicate:
        print("no `signal` in envelope — receipt stored, nothing to promote")

    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(
                f"duplicate={str(duplicate).lower()}\n"
                f"receipt_path={out}\n"
                f"promoted_event_id={promoted or ''}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
