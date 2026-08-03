"""Custom JSON Schema formats for the research-only evidence contract."""
from __future__ import annotations

import math
from typing import Any

from jsonschema import FormatChecker


def _is_finite_number(value: Any) -> bool:
    """Reject IEEE NaN and infinities while ignoring non-number instances."""
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    try:
        return bool(math.isfinite(value))
    except (TypeError, ValueError, OverflowError):
        return True


def register_finite_format() -> None:
    """Register the finite-number format for subsequently created checkers."""
    if "finite" not in FormatChecker.checkers:
        FormatChecker.checkers["finite"] = (_is_finite_number, ())
