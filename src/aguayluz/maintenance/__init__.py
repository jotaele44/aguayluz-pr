"""Deterministic, audit-first maintenance/audit layer for aguayluz-pr.

Vendored per-repo (these are independent repos with no shared dependency).
The shared module set — models, state, detect, corrections, quarantine, report —
is generic; ``adapters/local.py`` holds the repo-specific checks. ``runner`` wires
them together and emits ``reports/maintenance/latest.json``.
"""
from __future__ import annotations

from .models import MAINTENANCE_VERSION, MaintenanceFinding, MaintenanceReport
from .report import REPORT_RELPATH
from .runner import run_maintenance

__all__ = [
    "MAINTENANCE_VERSION",
    "MaintenanceFinding",
    "MaintenanceReport",
    "REPORT_RELPATH",
    "run_maintenance",
]
