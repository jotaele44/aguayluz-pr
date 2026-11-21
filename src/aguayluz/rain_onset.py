"""Deterministic rainfall onset detection; no network or notification side effects.

Input is independently verified station or radar-derived rain rate in mm/hour.
A municipality assignment requires an upstream authoritative spatial binding.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class RainPolicy:
    onset_rate_mm_h: float = 0.5
    confirmations: int = 2
    max_sample_gap_minutes: int = 30
    dry_reset_minutes: int = 60

    def __post_init__(self) -> None:
        if self.onset_rate_mm_h <= 0 or self.confirmations < 1:
            raise ValueError("invalid onset rate or confirmation count")
        if self.max_sample_gap_minutes <= 0 or self.dry_reset_minutes <= 0:
            raise ValueError("intervals must be positive")


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO-8601")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp requires a timezone")
    return dt.astimezone(timezone.utc)


def observe(state: dict[str, Any] | None, reading: dict[str, Any],
            policy: RainPolicy = RainPolicy()) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return (new_state, optional NEW_RAIN event); never mutate caller state.

    A stream is uniquely identified by source_id, station_id and municipality ID.
    Source updates must be chronological. Duplicates and older samples are ignored;
    prolonged gaps reset provisional confirmations, never synthesize continuity.
    """
    source_id = reading.get("source_id")
    station_id = reading.get("station_id")
    municipio_id = reading.get("municipio_id")
    source_ref = reading.get("source_ref")
    if not all(isinstance(v, str) and v.strip() for v in
               (source_id, station_id, municipio_id, source_ref)):
        raise ValueError("source, station, municipality and source_ref are required")
    rate = reading.get("rate_mm_h")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        raise ValueError("rain rate must be numeric")
    import math
    if not math.isfinite(rate) or rate < 0:
        raise ValueError("rain rate must be finite and nonnegative")
    at = parse_time(reading.get("observed_at"))
    key = "|".join((source_id, station_id, municipio_id))
    old = dict(state or {})
    if old and old.get("stream_key") != key:
        raise ValueError("state belongs to another stream")
    last = parse_time(old["last_seen"]) if old.get("last_seen") else None
    if last and at <= last:
        return old, None

    wet = rate >= policy.onset_rate_mm_h
    count = int(old.get("wet_count", 0))
    active = bool(old.get("active", False))
    episode_start = old.get("episode_start")
    dry_since = parse_time(old["dry_since"]) if old.get("dry_since") else None
    gap = (at - last) if last else None
    if gap is not None and gap > timedelta(minutes=policy.max_sample_gap_minutes):
        count = 0
        # An uncertain gap cannot establish a dry spell or another new onset.
        if active:
            episode_start = old.get("episode_start")
    event = None
    if wet:
        if not active:
            count += 1
            if count == 1:
                episode_start = at.isoformat()
            if count >= policy.confirmations:
                active = True
                event_key = "|".join((key, episode_start or at.isoformat()))
                event = {
                    "event_id": "AYL_RAIN_" + hashlib.sha256(event_key.encode()).hexdigest()[:24],
                    "event_type": "NEW_RAIN",
                    "module_id": "WEATHER_HAZARD",
                    "source_ref": source_ref,
                    "source_id": source_id,
                    "station_id": station_id,
                    "municipio_id": municipio_id,
                    "first_observed_at": episode_start,
                    "confirmed_at": at.isoformat(),
                    "rate_mm_h": float(rate),
                    "alert_class": "observation_not_official_warning",
                }
        dry_since = None
    else:
        count = 0
        if dry_since is None:
            dry_since = at
        if active and (at - dry_since) >= timedelta(minutes=policy.dry_reset_minutes):
            active = False
            episode_start = None
    new = {"stream_key": key, "last_seen": at.isoformat(), "active": active,
           "wet_count": count, "dry_since": dry_since.isoformat() if dry_since else None,
           "episode_start": episode_start}
    return new, event
