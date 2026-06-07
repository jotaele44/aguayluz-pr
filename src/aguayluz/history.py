"""Run snapshots + diffs.

A *snapshot* freezes the current `outputs/*.json` entity files under
`outputs/history/<run_id>/` so a later diff can answer "what changed since
the last run." Geometry sidecars are NOT snapshotted (too heavy); only the
entity records that drive federation decisions.

A *diff* compares two snapshots and surfaces:
  - assets added / removed / changed (asset_id keyed)
  - events added / removed / changed (event_id keyed)
  - findings added / removed (finding_id keyed; M8 reconciliation)
  - headline summary used by the M15 federation handoff

Diff fields compared per-asset/per-event are deliberately narrow — the spec's
review-status fields and operational status are the ones that drive
federation actions. Pure metadata changes (e.g. source_hash regenerated) are
intentionally ignored to keep diff noise low.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Entity files snapshotted on every run. Excludes:
#   - geometry/ sidecars (too heavy, would dwarf the snapshot)
#   - base44_export.json (a derived view, not source-of-truth)
#   - integration_report.json (derived; carries the run_id we already encode)
_SNAPSHOT_FILES = (
    "utility_assets.json",
    "service_events.json",
    "source_manifest.json",
    "review_queue.json",
    "bridge_summary.json",
    "dependency_graph.json",
    "reconciliation_report.json",
    "watershed_delineation.json",
)

# Per-record fields whose changes are surfaced in diff output.
# We deliberately leave out source_hash / confidence (noisy) and lat/lon
# (rarely change for the same asset_id).
_ASSET_DIFF_FIELDS = (
    "status", "review_status", "attribute_coverage", "comid", "reachcode",
    "asset_type", "asset_subtype", "municipality", "operator",
)
_EVENT_DIFF_FIELDS = (
    "event_type", "review_status", "start_time", "end_time",
    "reported_customers_or_users", "notes",
)


def snapshot_run(
    outputs_dir: Path,
    run_id: str,
    *,
    history_root: Path | None = None,
) -> Path:
    """Copy the snapshot-tracked entity files to `outputs/history/<run_id>/`.

    Returns the per-run history directory. Files that don't exist in the
    current run are skipped (no-error) so the same snapshotter handles
    partial runs (e.g. ingest-only with no M7 graph yet).
    """
    history_root = history_root or (outputs_dir / "history")
    run_dir = history_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in _SNAPSHOT_FILES:
        src = outputs_dir / name
        if src.exists():
            shutil.copy2(src, run_dir / name)
    # Tombstone with a wall-clock timestamp so listing history is self-describing.
    (run_dir / "_snapshot_at.txt").write_text(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ\n"),
        encoding="utf-8",
    )
    return run_dir


def list_snapshots(history_root: Path) -> list[str]:
    """Return run_ids of available snapshots in chronological order (by name).

    Run IDs follow the YYYYMMDDTHHMMSSZ_<slug> pattern, so lexical sort = time sort.
    """
    if not history_root.exists():
        return []
    return sorted(p.name for p in history_root.iterdir() if p.is_dir())


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _index_by(records: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {r[key]: r for r in records if isinstance(r, dict) and key in r}


def _diff_records(
    a: dict[str, dict[str, Any]],
    b: dict[str, dict[str, Any]],
    *,
    id_key: str,
    fields: tuple[str, ...],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed: list[dict[str, Any]] = []
    for rid in sorted(set(a) & set(b)):
        rec_a, rec_b = a[rid], b[rid]
        for field in fields:
            if rec_a.get(field) != rec_b.get(field):
                changed.append({
                    id_key: rid,
                    "field": field,
                    "from": rec_a.get(field),
                    "to": rec_b.get(field),
                })
    return added, removed, changed


def _finding_set(report: dict[str, Any]) -> set[str]:
    findings = report.get("findings", []) if isinstance(report, dict) else []
    return {f["finding_id"] for f in findings if isinstance(f, dict) and "finding_id" in f}


def diff_runs(
    *,
    history_root: Path,
    run_from: str,
    run_to: str,
) -> dict[str, Any]:
    """Return a RunDiff dict comparing two snapshotted runs."""
    dir_from = history_root / run_from
    dir_to = history_root / run_to
    if not dir_from.exists():
        raise FileNotFoundError(f"snapshot not found: {dir_from}")
    if not dir_to.exists():
        raise FileNotFoundError(f"snapshot not found: {dir_to}")

    assets_a = _index_by(_load(dir_from / "utility_assets.json", []), "asset_id")
    assets_b = _index_by(_load(dir_to / "utility_assets.json", []), "asset_id")
    a_added, a_removed, a_changed = _diff_records(
        assets_a, assets_b, id_key="asset_id", fields=_ASSET_DIFF_FIELDS,
    )

    events_a = _index_by(_load(dir_from / "service_events.json", []), "event_id")
    events_b = _index_by(_load(dir_to / "service_events.json", []), "event_id")
    e_added, e_removed, e_changed = _diff_records(
        events_a, events_b, id_key="event_id", fields=_EVENT_DIFF_FIELDS,
    )

    findings_a = _finding_set(_load(dir_from / "reconciliation_report.json", {}))
    findings_b = _finding_set(_load(dir_to / "reconciliation_report.json", {}))
    f_added = sorted(findings_b - findings_a)
    f_removed = sorted(findings_a - findings_b)

    total = (
        len(a_added) + len(a_removed) + len(a_changed)
        + len(e_added) + len(e_removed) + len(e_changed)
        + len(f_added) + len(f_removed)
    )
    if total == 0:
        headline = "no changes between runs"
    else:
        parts: list[str] = []
        if a_added or a_removed or a_changed:
            parts.append(
                f"assets +{len(a_added)}/-{len(a_removed)}/~{len(a_changed)}"
            )
        if e_added or e_removed or e_changed:
            parts.append(
                f"events +{len(e_added)}/-{len(e_removed)}/~{len(e_changed)}"
            )
        if f_added or f_removed:
            parts.append(f"findings +{len(f_added)}/-{len(f_removed)}")
        headline = "; ".join(parts)

    return {
        "module_id": "aguayluz-pr",
        "run_from": run_from,
        "run_to": run_to,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "assets_added": a_added,
        "assets_removed": a_removed,
        "assets_changed": a_changed,
        "events_added": e_added,
        "events_removed": e_removed,
        "events_changed": e_changed,
        "findings_added": f_added,
        "findings_removed": f_removed,
        "summary": {"total_changes": total, "headline": headline},
    }
