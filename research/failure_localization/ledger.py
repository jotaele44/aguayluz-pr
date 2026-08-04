"""Append-only JSONL storage for failure localization."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import canonical_json, digest


class AppendOnlyLocalizationLedger:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def read(self, stream: str) -> list[dict[str, Any]]:
        path = self.root / f"{stream}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def latest(self, stream: str, key: str, value: str) -> dict[str, Any] | None:
        return next(
            (row for row in reversed(self.read(stream)) if str(row.get(key)) == value),
            None,
        )

    def append(self, stream: str, record: dict[str, Any]) -> dict[str, Any]:
        row = copy.deepcopy(record)
        row.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        row.setdefault("record_hash", digest(row))
        with (self.root / f"{stream}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(row) + "\n")
        return row

    def append_idempotent(
        self, stream: str, record: dict[str, Any], *, idempotency_key: str
    ) -> dict[str, Any]:
        payload_hash = digest(record)
        prior = self.latest(stream, "idempotency_key", idempotency_key)
        if prior:
            if prior.get("payload_hash") != payload_hash:
                raise ValueError(f"{stream}_idempotency_conflict")
            return {**prior, "replayed": True}
        return self.append(stream, {
            **record, "idempotency_key": idempotency_key,
            "payload_hash": payload_hash, "replayed": False,
        })
