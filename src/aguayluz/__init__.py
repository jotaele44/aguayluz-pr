"""aguayluz-pr — PR water/power/utility infrastructure intelligence producer."""

from __future__ import annotations

import os

__version__ = "0.1.0"
__module_id__ = "aguayluz-pr"

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
CONFIG_DIR = REPO_ROOT / "config"
_workspace = os.getenv("AGUAYLUZ_DATA_HOME", "").strip()
OUTPUTS_DIR = Path(_workspace) / "exports" if _workspace else REPO_ROOT / "outputs"
DATA_DIR = Path(_workspace) / "data" if _workspace else REPO_ROOT / "data"

__all__ = [
    "__version__",
    "__module_id__",
    "REPO_ROOT",
    "SCHEMAS_DIR",
    "CONFIG_DIR",
    "OUTPUTS_DIR",
    "DATA_DIR",
]
