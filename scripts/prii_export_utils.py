"""Small deterministic helpers for PRII federation export scripts."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
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
