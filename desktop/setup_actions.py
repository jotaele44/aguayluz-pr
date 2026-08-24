"""Idempotent writable-workspace preparation invoked by the native setup UI."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_missing_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def prepare_workspace() -> None:
    """Seed bundled read-only datasets without replacing user-generated files."""
    workspace = Path(os.environ["AGUAYLUZ_DATA_HOME"])
    _copy_missing_tree(REPO_ROOT / "data", workspace / "data")
    _copy_missing_tree(REPO_ROOT / "outputs", workspace / "exports")
