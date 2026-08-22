"""Fail-closed water-balance interval builder.

This module intentionally refuses to infer balance roles from metric names alone.
Callers must provide an explicit role map keyed by reading id or by
``asset_id|metric|parameter_code``.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

Role = Literal["inflow", "outflow", "storage"]

MILLION_GALLONS_PER_CFS_DAY = 0.646316883


@dataclass(frozen=True)
class BalanceInput:
    reading: dict[str, Any]
    role: Role
    volume_mgal: float


def stable_digest(*parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def role_for(reading: dict[str, Any], role_map: dict[str, Role]) -> Role | None:
    reading_id = str(reading.get("reading_id") or "")
    if reading_id in role_map:
        return role_map[reading_id]
    key = "|".join(
        [
            str(reading.get("asset_id") or ""),
            str(reading.get("metric") or ""),
            str(reading.get("parameter_code") or ""),
        ]
    )
    return role_map.get(key)


def quarantine_record(reading: dict[str, Any], code: str) -> dict[str, Any]:
    digest = stable_digest(
        "water_balance_quarantine",
        reading.get("asset_id"),
        reading.get("reading_id"),
        reading.get("observed_date"),
        code,
        reading,
    )[:24]
    return {
        "quarantine_id": f"AYL_WBAL_Q_{digest}",
        "asset_id": str(reading.get("asset_id") or "UNKNOWN_ASSET"),
        "reading_id": reading.get("reading_id"),
        "observed_date": reading.get("observed_date"),
        "quarantine_code": code,
        "source_ref": reading.get("source_ref"),
        "source_hash": reading.get("source_hash"),
        "raw_record": reading,
        "review_status": "blocked",
    }


def _parse_day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _usable_source_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _to_mgal(reading: dict[str, Any], role: Role, interval_days: float) -> float | None:
    try:
        value = float(reading["value"])
    except (KeyError, TypeError, ValueError):
        return None
    unit = str(reading.get("unit") or "").strip().lower()
    if unit in {"mgal", "mg", "million gallons", "million_gallons"}:
        return value
    if role in {"inflow", "outflow"} and unit in {"mgd", "mgal/d", "mgal/day", "million gallons per day"}:
        return value * interval_days
    if role in {"inflow", "outflow"} and unit in {"ft3/s", "cfs"}:
        return value * MILLION_GALLONS_PER_CFS_DAY * interval_days
    return None


def admit_reading(
    reading: dict[str, Any],
    role_map: dict[str, Role],
    *,
    interval_days: float,
    production_mode: bool = True,
) -> tuple[BalanceInput | None, list[dict[str, Any]]]:
    quarantines: list[dict[str, Any]] = []
    role = role_for(reading, role_map)
    if role is None:
        quarantines.append(quarantine_record(reading, "NO_EXPLICIT_BALANCE_ROLE"))
    if production_mode and (
        reading.get("synthetic") is True
        or reading.get("fixture_only") is True
        or "tests/fixtures" in str(reading.get("source_ref") or "")
    ):
        quarantines.append(quarantine_record(reading, "SYNTHETIC_PRODUCTION_INPUT"))
    if not reading.get("reading_id"):
        quarantines.append(quarantine_record(reading, "MISSING_READING_ID"))
    if not reading.get("asset_id"):
        quarantines.append(quarantine_record(reading, "MISSING_ASSET_ID"))
    if _parse_day(reading.get("observed_date")) is None:
        quarantines.append(quarantine_record(reading, "INVALID_OBSERVED_DATE"))
    if not _usable_source_hash(reading.get("source_hash")):
        quarantines.append(quarantine_record(reading, "MISSING_SOURCE_HASH"))
    if reading.get("confidence") is None:
        quarantines.append(quarantine_record(reading, "MISSING_CONFIDENCE"))
    confidence_value = reading.get("confidence")
    try:
        confidence = int(confidence_value) if confidence_value is not None else -1
    except (TypeError, ValueError):
        quarantines.append(quarantine_record(reading, "INVALID_CONFIDENCE"))
    else:
        if not 0 <= confidence <= 100:
            quarantines.append(quarantine_record(reading, "INVALID_CONFIDENCE"))

    if role is None:
        return None, quarantines
    volume = _to_mgal(reading, role, interval_days)
    if volume is None:
        quarantines.append(quarantine_record(reading, "UNIT_NOT_BALANCE_VOLUME"))
        return None, quarantines
    if quarantines:
        return None, quarantines
    return BalanceInput(reading=reading, role=role, volume_mgal=volume), []


def build_balance_intervals(
    readings: list[dict[str, Any]],
    role_map: dict[str, Role],
    *,
    interval_start: str,
    interval_end: str,
    production_mode: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    start = _parse_day(interval_start)
    end = _parse_day(interval_end)
    if start is None or end is None or end < start:
        raise ValueError("interval_start and interval_end must be valid dates with end >= start")
    interval_days = (end - start).days + 1
    grouped: dict[str, list[BalanceInput]] = defaultdict(list)
    quarantines: list[dict[str, Any]] = []

    for reading in readings:
        observed = _parse_day(reading.get("observed_date"))
        if observed is None or not (start <= observed <= end):
            continue
        admitted, qrows = admit_reading(
            reading,
            role_map,
            interval_days=float(interval_days),
            production_mode=production_mode,
        )
        quarantines.extend(qrows)
        if admitted is not None:
            grouped[str(reading["asset_id"])].append(admitted)

    intervals: list[dict[str, Any]] = []
    quarantined_assets = {q["asset_id"] for q in quarantines}
    for asset_id, inputs in sorted(grouped.items()):
        by_role: dict[str, float] = defaultdict(float)
        reading_ids: list[str] = []
        source_hashes: list[str] = []
        confidence_values: list[int] = []
        tiers: list[str] = []
        for item in inputs:
            by_role[item.role] += item.volume_mgal
            reading_ids.append(str(item.reading["reading_id"]))
            source_hashes.append(str(item.reading["source_hash"]))
            confidence_values.append(int(item.reading["confidence"]))
            tiers.append(str(item.reading.get("evidence_tier") or "T4"))

        missing_roles = [role for role in ("inflow", "outflow") if role not in by_role]
        status = "accepted"
        qcodes: list[str] = []
        if missing_roles:
            status = "blocked"
            qcodes.extend(f"MISSING_{role.upper()}_INPUT" for role in missing_roles)
        elif "storage" not in by_role:
            status = "degraded"
            qcodes.append("MISSING_STORAGE_DELTA")
        if asset_id in quarantined_assets:
            status = "blocked"
            qcodes.append("ASSET_HAS_QUARANTINED_INPUTS")

        inflow = by_role.get("inflow")
        outflow = by_role.get("outflow")
        storage = by_role.get("storage")
        unaccounted = None
        if inflow is not None and outflow is not None:
            unaccounted = inflow - outflow - (storage or 0.0)
        combined_hash = stable_digest("water_balance_interval_sources", sorted(source_hashes))
        confidence = min(confidence_values) if confidence_values else 0
        tier = sorted(tiers)[-1] if tiers else "T4"
        intervals.append(
            {
                "interval_id": f"AYL_WBAL_{start:%Y%m%d}_{end:%Y%m%d}_{asset_id}",
                "asset_id": asset_id,
                "interval_start": interval_start,
                "interval_end": interval_end,
                "interval_days": float(interval_days),
                "balance_status": status,
                "unit": "Mgal",
                "input_reading_ids": sorted(set(reading_ids)),
                "inflow_volume": round(inflow, 6) if inflow is not None else None,
                "outflow_volume": round(outflow, 6) if outflow is not None else None,
                "storage_delta": round(storage, 6) if storage is not None else None,
                "unaccounted_volume": round(unaccounted, 6) if unaccounted is not None else None,
                "source_hash": combined_hash,
                "evidence_tier": tier,
                "confidence": confidence,
                "review_status": "accepted" if status == "accepted" else "blocked" if status == "blocked" else "needs_review",
                "quarantine_codes": sorted(set(qcodes)),
            }
        )
    return intervals, quarantines
