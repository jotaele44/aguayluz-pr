"""Bounded import helpers for verified occurrence and structured survey rows."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from typing import Any

REQUIRED_SURVEY_FIELDS = frozenset({"survey_id", "site_id", "started_at", "observer", "method", "effort_minutes", "detection_status"})


def read_jsonl(payload: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(payload.decode("utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"jsonl_row_{line_number}_not_object")
        rows.append(value)
    return rows


def read_survey_csv(payload: bytes) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    missing = REQUIRED_SURVEY_FIELDS - set(reader.fieldnames or ())
    if missing:
        raise ValueError({"missing_survey_columns": sorted(missing)})
    rows: list[dict[str, Any]] = []
    for row in reader:
        normalized = {key: (value.strip() if isinstance(value, str) else value) for key, value in row.items()}
        normalized["effort_minutes"] = float(normalized["effort_minutes"])
        rows.append(normalized)
    return rows


def account_rows(rows: Iterable[dict[str, Any]], required: frozenset[str]) -> dict[str, int]:
    seen = accepted = rejected = 0
    for row in rows:
        seen += 1
        if required <= set(row) and all(row.get(key) not in (None, "") for key in required):
            accepted += 1
        else:
            rejected += 1
    return {"seen": seen, "accepted": accepted, "rejected": rejected}
