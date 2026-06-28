"""Audit-first maintenance orchestration for aguayluz-pr.

collect state -> generic detectors -> repo adapter checks -> report.
Auto-correction only happens in explicit ``safe-correct`` mode.
"""
from __future__ import annotations

from pathlib import Path

from .. import REPO_ROOT, __module_id__
from . import corrections, detect
from . import state as state_mod
from .adapters import local
from .models import MaintenanceReport
from .quarantine import write_review_queue
from .report import write_latest_report

VALID_MODES = ("audit", "safe-correct")


def run_maintenance(
    root: str | Path | None = None,
    mode: str = "audit",
    write: bool = True,
) -> MaintenanceReport:
    if mode not in VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {VALID_MODES}")
    root_path = Path(root) if root is not None else REPO_ROOT
    repo = __module_id__
    state = state_mod.collect_repo_state(root_path)

    findings = []
    findings += detect.detect_missing_required_files(repo, root_path, state)
    findings += detect.detect_invalid_json(repo, root_path, state)
    findings += detect.detect_exact_duplicate_jsonl(repo, root_path, state)
    findings += local.run_checks(repo, root_path, state)

    if mode == "safe-correct":
        for finding in corrections.plan_safe_corrections(findings):
            if not finding.path:
                continue
            removed = corrections.remove_exact_duplicate_jsonl_rows(root_path / finding.path)
            if removed:
                finding.action = "auto_corrected"
                finding.detail = {**(finding.detail or {}), "rows_removed": removed}

    report = MaintenanceReport(repo=repo, findings=findings, mode=mode)
    if write:
        write_latest_report(report, root_path)
        write_review_queue(repo, findings, root_path)
    return report
