"""Staged ionosphere contract. No live provider or grid-impact claims."""
from __future__ import annotations

import math
from datetime import datetime, timezone

SOURCE_URL = "https://www.spaceweather.gov/products/glotec"
DATA_URL = "https://services.swpc.noaa.gov/products/glotec/geojson_2d_urt/"


def audit_status() -> dict:
    """Return known acquisition gates, never synthetic observations."""
    return {
        "state": "BLOCKED", "measurements": None, "freshness": "NEVER",
        "source_url": SOURCE_URL, "data_url": DATA_URL,
        "tec": {"state": "BLOCKED", "reason": "HTTP 403 during source audit; live schema and Puerto Rico cells unverified",
                "kind": "MODEL", "units": "TECU", "resolution_degrees": [2.5, 5.0]},
        "roti": {"state": "UNRESOLVED", "reason": "Puerto Rico provider, coverage and calculation window unverified"},
        "acquisition_attempt": {"date": "2026-10-23", "http_status": 403, "is_live_health_check": False},
        "claims": {"municipality_measurements": False, "grid_damage": False,
                   "service_outage": False, "live_integration": False},
    }


def validate_record(row: dict, now: datetime, max_age_seconds: int = 1800) -> dict:
    """Validate a proposed shared producer record; not a NOAA raw-schema adapter.

    Preserve the whole row. Provider validation, geometry binding and ingestion
    remain separate gates. ROTI cannot be manufactured from coarse modeled TEC.
    """
    if now.tzinfo is None or max_age_seconds <= 0:
        raise ValueError("aware clock and positive freshness limit required")
    required = {"id", "metric", "value", "units", "observed_at", "retrieved_at",
                "source_url", "source_sha256", "kind", "quality", "longitude", "latitude"}
    if not isinstance(row, dict) or not required <= row.keys():
        raise ValueError("missing required contract fields")
    if not isinstance(row["id"], str) or not row["id"].strip():
        raise ValueError("missing stable producer ID")
    metric = row["metric"]
    if metric not in {"TEC", "ROTI"}:
        raise ValueError("unknown metric")
    expected = "TECU" if metric == "TEC" else "TECU/min"
    if row["units"] != expected or row["kind"] not in {"MODEL", "OBSERVATION"}:
        raise ValueError("invalid units or record kind")
    if row["kind"] == "MODEL" and metric == "ROTI":
        raise ValueError("ROTI requires a validated observational method")
    if row["quality"] not in {"UNKNOWN", "VALID", "SUSPECT", "INVALID"}:
        raise ValueError("invalid quality state")
    import re
    if not isinstance(row["source_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]):
        raise ValueError("invalid source digest")
    from urllib.parse import urlsplit
    if not isinstance(row["source_url"], str):
        raise ValueError("invalid source URL")
    url = urlsplit(row["source_url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("HTTPS provenance required")
    for field, low, high in (("longitude", -180, 180), ("latitude", -90, 90)):
        value = row[field]
        if type(value) not in {int, float} or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("invalid coordinates")
    value = row["value"]
    if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or value < 0):
        raise ValueError("invalid measurement")
    stamps = []
    for field in ("observed_at", "retrieved_at"):
        try:
            stamp = datetime.fromisoformat(row[field].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("invalid timestamp") from exc
        if stamp.tzinfo is None or stamp > now:
            raise ValueError("naive or future timestamp")
        stamps.append(stamp)
    if stamps[1] < stamps[0]:
        raise ValueError("retrieval precedes observation")
    if metric == "ROTI":
        window = row.get("window_seconds")
        if type(window) not in {int, float} or not math.isfinite(window) or window <= 0:
            raise ValueError("ROTI calculation window required")
        if not isinstance(row.get("method"), str) or not row["method"].strip():
            raise ValueError("ROTI method required")
    age = (now.astimezone(timezone.utc) - stamps[0]).total_seconds()
    state = "MISSING" if value is None else "STALE" if age > max_age_seconds else "FRESH"
    return {"raw_record": dict(row), "freshness": state, "quality": row["quality"],
            "spatial_binding": "UNRESOLVED", "impact": "UNKNOWN"}


def validate_batch(rows: list[dict], now: datetime) -> list[dict]:
    """Reject duplicate IDs rather than choose a winner or multiply rows."""
    result = [validate_record(row, now) for row in rows]
    ids = [row["raw_record"]["id"] for row in result]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate producer IDs")
    return result
