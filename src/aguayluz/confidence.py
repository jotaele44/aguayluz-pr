"""Tier-anchored confidence scorer.

Centralized so every entity producer agrees on the formula. Override the
defaults via a config-driven weight table later if needed.
"""

from __future__ import annotations

from typing import Literal

EvidenceTier = Literal["T1", "T2", "T3", "T4"]
AttributeCoverage = Literal["full", "partial"]

TIER_BASE: dict[EvidenceTier, int] = {
    "T1": 80,
    "T2": 60,
    "T3": 45,
    "T4": 30,
}

PARTIAL_COVERAGE_PENALTY = 10
MISSING_COORDS_PENALTY = 15
MULTI_SOURCE_BONUS_PER_EXTRA = 3
MULTI_SOURCE_BONUS_CAP = 12


def score(
    tier: EvidenceTier,
    source_count: int = 1,
    has_coords: bool = True,
    attribute_coverage: AttributeCoverage = "full",
) -> int:
    """Return an integer confidence 0..100.

    `source_count` of 2+ adds +3 per extra source up to +12.
    `has_coords=False` deducts 15.
    `attribute_coverage="partial"` deducts 10 (e.g. VPU 21 NHDPlus extensions missing).
    """
    base = TIER_BASE[tier]
    extras = max(0, source_count - 1)
    bonus = min(MULTI_SOURCE_BONUS_CAP, extras * MULTI_SOURCE_BONUS_PER_EXTRA)
    penalty = 0
    if not has_coords:
        penalty += MISSING_COORDS_PENALTY
    if attribute_coverage == "partial":
        penalty += PARTIAL_COVERAGE_PENALTY
    return max(0, min(100, base + bonus - penalty))
