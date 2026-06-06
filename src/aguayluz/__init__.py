"""aguayluz-pr — PR water/power/utility infrastructure intelligence producer."""

from __future__ import annotations

__version__ = "0.1.0"
__module_id__ = "aguayluz-pr"

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
CONFIG_DIR = REPO_ROOT / "config"
OUTPUTS_DIR = REPO_ROOT / "outputs"

__all__ = [
    "__version__",
    "__module_id__",
    "REPO_ROOT",
    "SCHEMAS_DIR",
    "CONFIG_DIR",
    "OUTPUTS_DIR",
]
