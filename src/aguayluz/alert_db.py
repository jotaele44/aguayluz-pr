"""Loaders, SQLite builder, and GeoJSON projection for the alert system.

Keeps I/O logic out of ``scripts/build_alert_system.py`` and the CLI so it is
importable and unit-testable. SQLite is the portable analysis store; the DDL in
``schemas/sql/alert_system.sql`` is PostGIS-ready for the production graph.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from . import CONFIG_DIR, DATA_DIR, SCHEMAS_DIR
from .alert_validation import AlertValidationResult, validate_alerts
from .models import validate_against_schema

DDL_PATH = SCHEMAS_DIR / "sql" / "alert_system.sql"
MODULES_PATH = CONFIG_DIR / "alert_modules.yaml"
EVENTS_PATH = DATA_DIR / "alert_events.jsonl"
EDGES_PATH = DATA_DIR / "alert_dependency_edges.jsonl"
GAPS_PATH = DATA_DIR / "alert_gaps.jsonl"

# Event columns whose values are arrays -> stored as JSON text in SQLite.
_EVENT_JSON_FIELDS = ("municipalities", "sectors_impacted", "covert_flags", "linked_asset_ids")
_EVENT_COLUMNS = (
    "alert_id", "module_id", "event_type", "status", "source_title", "source_ref",
    "source_hash", "published_at", "start_at", "end_at", "estimated_duration_hr",
    "asset_name", "asset_id", "operator", "municipalities", "sectors_impacted",
    "latitude", "longitude", "coord_confidence", "severity", "confidence",
    "ilap_score", "covert_flags", "gap_status", "review_status", "evidence_tier",
    "linked_asset_ids", "validation_notes",
)
_MODULE_COLUMNS = (
    "module_id", "module_name", "sector", "activation_status", "priority",
    "hydro_dependency_relevance", "default_severity_floor", "primary_sources", "notes",
)
_EDGE_COLUMNS = (
    "edge_id", "from_node_type", "from_node_id", "to_node_type", "to_node_id",
    "dependency_type", "confidence", "evidence_required", "notes",
)
_GAP_COLUMNS = (
    "gap_id", "alert_id", "module_id", "gap_type", "severity", "blocking",
    "description", "next_action", "status",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_modules(path: Path = MODULES_PATH) -> list[dict[str, Any]]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8")).get("modules", [])
    for r in rows:
        validate_against_schema("alert_module", r)
    return rows


def load_events(path: Path = EVENTS_PATH) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    for r in rows:
        validate_against_schema("alert_event", r)
    return rows


def load_edges(path: Path = EDGES_PATH) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    for r in rows:
        validate_against_schema("alert_dependency_edge", r)
    return rows


def load_gaps(path: Path = GAPS_PATH) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    for r in rows:
        validate_against_schema("alert_gap", r)
    return rows


def _event_row(e: dict[str, Any]) -> tuple:
    return tuple(
        json.dumps(e.get(c, []), ensure_ascii=False) if c in _EVENT_JSON_FIELDS else e.get(c)
        for c in _EVENT_COLUMNS
    )


def _insert(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], row: tuple) -> None:
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", row
    )


def build_sqlite(
    db_path: str | Path = ":memory:",
    *,
    modules: list[dict] | None = None,
    events: list[dict] | None = None,
    edges: list[dict] | None = None,
    gaps: list[dict] | None = None,
) -> sqlite3.Connection:
    """Create the alert-system SQLite DB from the DDL and load the seeds.

    Returns the open connection (caller closes). Pass a file path to persist;
    defaults to an in-memory DB for tests/CLI dry runs.
    """
    modules = load_modules() if modules is None else modules
    events = load_events() if events is None else events
    edges = load_edges() if edges is None else edges
    gaps = load_gaps() if gaps is None else gaps

    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL_PATH.read_text(encoding="utf-8"))

    for m in modules:
        _insert(conn, "alert_modules", _MODULE_COLUMNS, tuple(m.get(c) for c in _MODULE_COLUMNS))
    for e in events:
        _insert(conn, "alert_events", _EVENT_COLUMNS, _event_row(e))
    for ed in edges:
        row = tuple(int(ed[c]) if c == "evidence_required" else ed.get(c) for c in _EDGE_COLUMNS)
        _insert(conn, "alert_dependency_edges", _EDGE_COLUMNS, row)
    for g in gaps:
        row = tuple(int(g[c]) if c == "blocking" else g.get(c) for c in _GAP_COLUMNS)
        _insert(conn, "alert_gaps", _GAP_COLUMNS, row)
    conn.commit()
    return conn


def events_to_geojson(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Project georeferenced alert events to a GeoJSON FeatureCollection."""
    features = []
    for e in events:
        if e.get("latitude") is None or e.get("longitude") is None:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "alert_id": e["alert_id"],
                    "module_id": e["module_id"],
                    "asset_name": e["asset_name"],
                    "event_type": e["event_type"],
                    "coord_confidence": e["coord_confidence"],
                    "severity": e["severity"],
                    "confidence": e["confidence"],
                    "gap_status": e["gap_status"],
                    "review_status": e["review_status"],
                },
                "geometry": {"type": "Point", "coordinates": [e["longitude"], e["latitude"]]},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def validate_seed_events(events: list[dict] | None = None) -> list[AlertValidationResult]:
    """Run VAL-001..010 over the seed events (or a provided list)."""
    return validate_alerts(load_events() if events is None else events)
