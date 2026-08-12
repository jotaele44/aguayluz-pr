"""Canonical constants, receipts, and observation construction."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA_VERSION = "aguayluz.laguna-cartagena-observation/v0.2"
USER_AGENT = "aguayluz-pr-laguna-cartagena-probe/0.3"
DIRECT_SITE_IDS = ("50129899", "50129900", "180046067053700")
CANAL_SITE_IDS = ("50128905", "50128940")
ALL_USGS_SITE_IDS = (*DIRECT_SITE_IDS, *CANAL_SITE_IDS)
NEON_SITE = "LAJA"
NEON_PRODUCTS = ("DP1.00044.001", "DP1.00045.001", "DP1.00094.001")

SITE_METADATA: dict[str, dict[str, Any]] = {
    "50129899": {
        "name": "Laguna Cartagena near Boquerón",
        "municipality": "Lajas",
        "direct_or_proxy": "direct",
        "representativeness": "direct",
        "metric_by_parameter": {
            "00065": "lagoon_stage",
            "00095": "specific_conductance",
            "00010": "water_temperature",
            "00300": "dissolved_oxygen",
            "00400": "ph",
            "63680": "turbidity",
        },
    },
    "50129900": {
        "name": "Laguna Cartagena outflow near Boquerón",
        "municipality": "Cabo Rojo",
        "direct_or_proxy": "direct",
        "representativeness": "direct",
        "metric_by_parameter": {
            "00060": "outflow_discharge",
            "00095": "specific_conductance",
            "00010": "water_temperature",
            "00300": "dissolved_oxygen",
            "00400": "ph",
            "63680": "turbidity",
        },
    },
    "180046067053700": {
        "name": "Laguna Cartagena well",
        "municipality": "Lajas",
        "direct_or_proxy": "direct",
        "representativeness": "direct",
        "metric_by_parameter": {
            "72019": "groundwater_level",
            "62610": "groundwater_level",
            "00095": "specific_conductance",
            "00010": "water_temperature",
        },
    },
    "50128905": {
        "name": "Lajas irrigation canal below Lago Loco Dam",
        "municipality": "Lajas",
        "direct_or_proxy": "proxy",
        "representativeness": "medium",
        "metric_by_parameter": {"00060": "canal_release"},
    },
    "50128940": {
        "name": "Lajas irrigation canal downstream operational gage",
        "municipality": "Lajas",
        "direct_or_proxy": "proxy",
        "representativeness": "medium",
        "metric_by_parameter": {"00060": "terminal_flow"},
    },
}

WQ_CHARACTERISTIC_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"specific conduct", re.I), "specific_conductance"),
    (re.compile(r"temperature.*water|water temperature", re.I), "water_temperature"),
    (re.compile(r"dissolved oxygen|oxygen, dissolved", re.I), "dissolved_oxygen"),
    (re.compile(r"^ph$|ph,", re.I), "ph"),
    (re.compile(r"turbidity", re.I), "turbidity"),
    (re.compile(r"nitrate|nitrite.*nitrate", re.I), "nitrate"),
    (re.compile(r"ammonia|ammonium", re.I), "ammonia"),
    (re.compile(r"phosph", re.I), "phosphorus"),
    (re.compile(r"e\.\s*coli|fecal coliform|enterococc", re.I), "fecal_indicator"),
)


@dataclass(frozen=True)
class FetchReceipt:
    source_id: str
    provider: str
    url: str
    retrieved_at: str
    http_status: int | None
    content_type: str | None
    etag: str | None
    last_modified: str | None
    byte_count: int
    sha256: str
    raw_path: str
    error: str | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_token(*parts: Any, length: int = 24) -> str:
    return sha256_bytes(canonical_json(parts).encode("utf-8"))[:length]


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")[:120] or "response"


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def normalize_unit(unit: str, metric: str) -> str:
    aliases = {
        "ft3/s": "ft3/s",
        "ft^3/s": "ft3/s",
        "cfs": "ft3/s",
        "deg c": "degC",
        "degree celsius": "degC",
        "degrees celsius": "degC",
        "us/cm": "uS/cm",
        "µs/cm": "uS/cm",
        "ntu": "NTU",
        "mg/l": "mg/L",
        "count/100 ml": "count/100mL",
    }
    if metric == "ph":
        return "standard_units"
    cleaned = unit.strip()
    return aliases.get(cleaned.lower(), cleaned)


def build_observation(
    *,
    source_id: str,
    source_record_id: str,
    source_hash: str,
    provider: str,
    location_id: str,
    metric: str,
    value: float | str | bool,
    unit: str,
    observed_at: datetime,
    window_id: str,
    qa_status: str = "provisional",
    method: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    meta = SITE_METADATA[location_id]
    freshness = timedelta(hours=36 if metric in {"canal_release", "terminal_flow"} else 72)
    if metric in {
        "specific_conductance",
        "water_temperature",
        "dissolved_oxygen",
        "ph",
        "turbidity",
        "nitrate",
        "ammonia",
        "phosphorus",
        "fecal_indicator",
    }:
        freshness = timedelta(days=45)
    identity = {
        "provider": provider,
        "location_id": location_id,
        "metric": metric,
        "observed_at": observed_at.isoformat(),
        "source_record_id": source_record_id,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_id": f"AYL_LC_OBS_{stable_token(identity)}",
        "observation_window_id": window_id,
        "observed_at": observed_at.isoformat(),
        "valid_until": (observed_at + freshness).isoformat(),
        "source_id": source_id,
        "source_record_id": source_record_id,
        "source_hash": source_hash,
        "provider": provider,
        "location_id": location_id,
        "location_name": meta["name"],
        "municipality": meta["municipality"],
        "metric": metric,
        "value": value,
        "unit": normalize_unit(unit, metric),
        "evidence_tier": "T1",
        "direct_or_proxy": meta["direct_or_proxy"],
        "distance_from_target_km": 0 if meta["direct_or_proxy"] == "direct" else None,
        "hydrologic_representativeness": meta["representativeness"],
        "historical_baseline": False,
        "qa_status": qa_status,
        "provisional": qa_status == "provisional",
        "condition": "unknown",
        "threshold_provenance": "none",
        "method": method,
        "notes": notes,
        "evidence_ids": [f"EVID_{stable_token(source_id, source_record_id, source_hash)}"],
        "shadow_mode": True,
    }


def deduplicate_observations(observations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for observation in observations:
        selected.setdefault(str(observation["observation_id"]), observation)
    return sorted(selected.values(), key=lambda row: (row["observed_at"], row["observation_id"]))
