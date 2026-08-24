"""Fail-closed staging controls for the research-only ASGI surface."""
from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date

FEATURE_FLAG_ENV = "AGUAYLUZ_ENABLE_MYCELIAL_RESEARCH_API"
CAPABILITY_CLASSIFICATION = "internal_research_only"
TRACKING_REFERENCE = "aguayluz-pr#110"
STAGING_EXPIRES_ON = date(2026, 12, 31)


def feature_flag_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Require the exact value ``1``; all other states remain disabled."""
    values = os.environ if environment is None else environment
    return values.get(FEATURE_FLAG_ENV) == "1"


def staging_window_open(today: date | None = None) -> bool:
    """Fail closed after the bounded Phase 0 staging window expires."""
    effective_date = date.today() if today is None else today
    return effective_date <= STAGING_EXPIRES_ON
