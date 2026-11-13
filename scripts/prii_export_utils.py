"""Small deterministic helpers for PRII federation export scripts.

Scripts run with this directory first on ``sys.path``, so this module shadows the
pinned ``prii-export-utils`` package of the same name. ``fid``, ``norm`` and
``sha256`` below are this repo's own (federation ids depend on them, so they are
kept exactly as they are). Any other name, such as the ``source_monitors``
helpers (thehub-pr ADR 0013), is served from the pinned package through the
module ``__getattr__`` at the bottom.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import re
import sys
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any


def fid(prefix: str, *parts: Any) -> str:
    key = "|".join("" if part is None else str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]}"


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", "" if value is None else str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


_NAME = "prii_export_utils"
_PINNED: ModuleType | None = None


def _pinned_package() -> ModuleType:
    """The installed ``prii-export-utils`` package this module shadows.

    It is imported with the loader its own finder returns and under its real name, so
    it loads wherever the package lives: site-packages, a zip, or the PyInstaller
    archive the desktop build bundles it in, where there is no source file to reopen.
    This module holds that name in ``sys.modules``; it steps aside while the package
    and its submodules import, then takes the name back.
    """
    global _PINNED
    if _PINNED is None:
        here = Path(__file__).resolve().parent
        search = [p for p in sys.path if Path(p or ".").resolve() != here]
        spec = importlib.machinery.PathFinder.find_spec(_NAME, search)
        if spec is None or spec.loader is None or not spec.submodule_search_locations:
            raise ImportError("the pinned prii-export-utils package is not installed")
        module = importlib.util.module_from_spec(spec)
        shim = sys.modules.get(_NAME)
        sys.modules[_NAME] = module
        try:
            spec.loader.exec_module(module)
        finally:
            if shim is None:
                sys.modules.pop(_NAME, None)
            else:
                sys.modules[_NAME] = shim
        _PINNED = module
    return _PINNED


def __getattr__(name: str) -> Any:  # PEP 562: names this module does not define
    if name.startswith("__"):
        raise AttributeError(name)
    try:
        return getattr(_pinned_package(), name)
    except AttributeError:
        raise AttributeError(f"module 'prii_export_utils' has no attribute {name!r}") from None
