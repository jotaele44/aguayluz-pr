"""Launch AguaYLuz through the shared self-contained desktop runtime.

Only ``desktop/config.py`` is product-specific. Native setup, repair,
diagnostics, lifecycle, and CI smoke modes live in ``prii_desktop``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prii_desktop import DesktopConfig, launch  # noqa: E402

from desktop import config  # noqa: E402


def main() -> None:
    launch(DesktopConfig.from_module(config))


if __name__ == "__main__":
    main()
