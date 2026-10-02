"""Transactional local operator overrides, separate from the source corpus.

Connections are short-lived so multiple API workers and restarted processes read
the same committed state. Each update and its audit entry commit together.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NAMESPACES = {"asset", "event", "review"}
REVIEW_STATUSES = {"accepted", "needs_review", "rejected", "blocked"}
PATCH_VALUES = {
    "asset": {"review_status": REVIEW_STATUSES, "status": {"active", "inactive", "damaged", "planned", "unknown"}},
    "event": {"review_status": REVIEW_STATUSES, "resolution_status": {"open", "acknowledged", "resolved"}},
    "review": {"decision": {"accept", "reject", "skip"}, "source_binding": None},
}


def validate_patch(namespace: str, patch: Any) -> None:
    allowed = PATCH_VALUES[namespace]
    if not isinstance(patch, dict) or not patch or set(patch) - set(allowed):
        raise ValueError("Provide only supported mutable fields")
    if namespace == "review" and set(patch) != {"decision", "source_binding"}:
        raise ValueError("A decision and its current source binding are required; reload the review queue")
    for key, value in patch.items():
        if key == "source_binding":
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("Invalid source binding; reload the review queue")
        elif not isinstance(value, str) or value not in allowed[key]:
            raise ValueError("Invalid mutable field value")


class OperatorStateError(RuntimeError):
    """The store cannot safely serve or commit operator changes."""


class OperatorState:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self, *, write: bool = False) -> sqlite3.Connection:
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=5)
            try:
                conn.execute("PRAGMA synchronous = FULL")
                conn.execute("""CREATE TABLE IF NOT EXISTS operator_overrides (
                    namespace TEXT NOT NULL, record_id TEXT NOT NULL,
                    payload TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(namespace, record_id))""")
                conn.execute("""CREATE TABLE IF NOT EXISTS operator_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL, record_id TEXT NOT NULL,
                    patch TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            except Exception:
                conn.close()
                raise
            return conn
        return sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)

    def snapshot(self, namespace: str) -> dict[str, dict[str, Any]]:
        if namespace not in NAMESPACES:
            raise ValueError("unknown operator-state namespace")
        if not self.path.exists():
            return {}
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT record_id, payload, updated_at FROM operator_overrides WHERE namespace=?",
                    (namespace,),
                ).fetchall()
            result = {}
            for record_id, payload, updated_at in rows:
                values = json.loads(payload)
                validate_patch(namespace, values)
                result[record_id] = {"values": values, "updated_at": updated_at}
            return result
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise OperatorStateError("Local edit storage is unavailable; saved changes were not discarded.") from exc

    def update(self, namespace: str, record_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if namespace not in NAMESPACES or not record_id or not patch:
            raise ValueError("namespace, record ID, and nonempty patch are required")
        validate_patch(namespace, patch)
        patch_json = json.dumps(patch, sort_keys=True, allow_nan=False)
        try:
            with closing(self._connect(write=True)) as conn, conn:
                # Lock before reading: disjoint concurrent edits must not overwrite one another.
                conn.execute("BEGIN IMMEDIATE")
                updated_at = datetime.now(timezone.utc).isoformat()
                row = conn.execute(
                    "SELECT payload FROM operator_overrides WHERE namespace=? AND record_id=?",
                    (namespace, record_id),
                ).fetchone()
                values = json.loads(row[0]) if row else {}
                if row:
                    validate_patch(namespace, values)
                values.update(patch)
                conn.execute(
                    "INSERT INTO operator_overrides VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(namespace, record_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                    (namespace, record_id, json.dumps(values, sort_keys=True, allow_nan=False), updated_at),
                )
                conn.execute(
                    "INSERT INTO operator_audit(namespace, record_id, patch, updated_at) VALUES (?, ?, ?, ?)",
                    (namespace, record_id, patch_json, updated_at),
                )
            return {"values": values, "updated_at": updated_at}
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise OperatorStateError("Local edit could not be saved; retry after storage is available.") from exc

    def status(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"state": "not_initialized", "durable": True, "saved_records": 0, "audit_entries": 0, "last_saved_at": None}
        try:
            with closing(self._connect()) as conn:
                if conn.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                    raise ValueError("operator store integrity check failed")
                for namespace, payload in conn.execute("SELECT namespace, payload FROM operator_overrides"):
                    if namespace not in NAMESPACES:
                        raise ValueError("unknown stored namespace")
                    validate_patch(namespace, json.loads(payload))
                saved = conn.execute("SELECT count(*) FROM operator_overrides").fetchone()[0]
                count, latest = conn.execute("SELECT count(*), max(updated_at) FROM operator_audit").fetchone()
            return {"state": "ready", "durable": True, "saved_records": saved, "audit_entries": count, "last_saved_at": latest}
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise OperatorStateError("Local edit storage is unavailable; saved changes were not discarded.") from exc
