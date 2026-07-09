"""AguaYLuz-specific maintenance checks (workbook Adapter Rules).

- check_api_health_config: EPA_WATERS_API_KEY declared; live check skipped if absent.
- check_asset_lineage:     utility/infrastructure entities must carry source_ref.
- check_orphan_relationships: service_event linked_asset_ids must reference known assets.

All checks are read-only and audit-first; lineage/relationship problems are
quarantined (routed to the review queue), never auto-corrected.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from prii_maintenance import MaintenanceFinding


def _load_json_list(path: Path) -> list | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def check_api_health_config(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    keys = state["federation"].get("source_truth", {}).get("runtime_required_keys", [])
    findings: list[MaintenanceFinding] = []
    for key in keys:
        if not os.environ.get(key):
            findings.append(
                MaintenanceFinding(
                    finding_id=f"{repo}:dependency_drift:{key.lower()}",
                    repo=repo,
                    category="dependency_drift",
                    severity="warning",
                    action="none",
                    message=f"runtime key {key} not set; live API health check skipped",
                    detail={"key": key},
                )
            )
    return findings


def check_asset_lineage(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    assets = _load_json_list(root / "outputs" / "utility_assets.json")
    if assets is None:
        return findings
    for i, asset in enumerate(assets):
        if not isinstance(asset, dict) or not asset.get("source_ref"):
            aid = asset.get("asset_id", i) if isinstance(asset, dict) else i
            findings.append(
                MaintenanceFinding(
                    finding_id=f"{repo}:lineage:asset_{aid}",
                    repo=repo,
                    category="lineage",
                    severity="error",
                    action="quarantined",
                    message="utility asset missing source_ref",
                    path="outputs/utility_assets.json",
                    detail={"index": i, "asset_id": aid},
                )
            )
    return findings


def check_orphan_relationships(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    assets = _load_json_list(root / "outputs" / "utility_assets.json")
    events = _load_json_list(root / "outputs" / "service_events.json")
    if assets is None or events is None:
        return findings
    known = {a.get("asset_id") for a in assets if isinstance(a, dict)}
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        for aid in event.get("linked_asset_ids", []):
            if aid not in known:
                eid = event.get("event_id", i)
                findings.append(
                    MaintenanceFinding(
                        finding_id=f"{repo}:lineage:orphan_{eid}_{aid}",
                        repo=repo,
                        category="lineage",
                        severity="error",
                        action="quarantined",
                        message=f"service_event references unknown asset_id {aid}",
                        path="outputs/service_events.json",
                        detail={"event_id": eid, "asset_id": aid},
                    )
                )
    return findings


CHECKS = (check_api_health_config, check_asset_lineage, check_orphan_relationships)


def run_checks(repo: str, root: Path, state: dict) -> list[MaintenanceFinding]:
    findings: list[MaintenanceFinding] = []
    for check in CHECKS:
        findings.extend(check(repo, root, state))
    return findings
