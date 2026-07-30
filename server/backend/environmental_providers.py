"""Fail-closed environmental provider registry and metadata delta polling.

Network polling is opt-in. Tokens are read only from environment variables and are
never returned by API responses or persisted in snapshots.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DATA_DIR = Path(os.environ.get("AGUAYLUZ_DATA_DIR", "data"))
SNAPSHOT_PATH = DATA_DIR / "environmental_provider_snapshot.json"


@dataclass(frozen=True)
class Provider:
    code: str
    name: str
    tier: str
    endpoint: str
    auth_env: str | None = None
    auth_header: str | None = None
    enabled_env: str = "AGUAYLUZ_EXTERNAL_POLLING_ENABLED"
    scope: str = "Puerto Rico"


PROVIDERS: dict[str, Provider] = {
    "neon": Provider("neon", "NSF NEON Data API", "T1", "https://data.neonscience.org/api/v0/sites", "NEON_API_TOKEN", "X-API-Token", scope="GUAN, LAJA, CUPE, GUIL"),
    "usgs": Provider("usgs", "USGS Water Data APIs", "T1", "https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?f=json&limit=1"),
    "nws": Provider("nws", "NOAA/NWS API", "T1", "https://api.weather.gov/points/18.2208,-66.5901", auth_header="User-Agent"),
    "nasa": Provider("nasa", "NASA Earthdata (GPM/SMAP)", "T1", "https://cmr.earthdata.nasa.gov/search/collections.json?page_size=1&keyword=GPM"),
    "lter": Provider("lter", "Luquillo LTER / USFS", "T1", "https://portal.edirepository.org/nis/home.jsp"),
    "wqp": Provider("wqp", "EPA Water Quality Portal", "T1", "https://www.waterqualitydata.us/data/Station/search?statecode=US:72&mimeType=json&zip=no&providers=NWIS&providers=STORET"),
    "drna": Provider("drna", "Puerto Rico DRNA hydrology", "T1", "https://www.drna.pr.gov/"),
}

NEON_PR_SITES = (
    {"site_code": "GUAN", "site_name": "Guanica Forest", "site_type": "terrestrial"},
    {"site_code": "LAJA", "site_name": "Lajas Experimental Station", "site_type": "terrestrial"},
    {"site_code": "CUPE", "site_name": "Rio Cupeyes", "site_type": "aquatic"},
    {"site_code": "GUIL", "site_name": "Rio Yahuecas", "site_type": "aquatic"},
)


def provider_registry() -> list[dict[str, Any]]:
    return [{**asdict(provider), "configured": bool(provider.auth_env and os.getenv(provider.auth_env)) if provider.auth_env else True, "polling_enabled": os.getenv(provider.enabled_env, "").lower() == "true"} for provider in PROVIDERS.values()]


def _headers(provider: Provider) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "AguaYLuz/1.0 environmental-monitor"}
    if provider.auth_env and provider.auth_header:
        token = os.getenv(provider.auth_env)
        if token:
            headers[provider.auth_header] = token
    return headers


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def poll_provider(code: str, *, timeout: float = 15.0) -> dict[str, Any]:
    provider = PROVIDERS.get(code)
    if provider is None:
        raise KeyError(code)
    checked_at = datetime.now(timezone.utc).isoformat()
    if os.getenv(provider.enabled_env, "").lower() != "true":
        return {"provider": code, "status": "disabled", "checked_at": checked_at, "reason": "external_polling_disabled"}
    if provider.auth_env and not os.getenv(provider.auth_env):
        return {"provider": code, "status": "blocked", "checked_at": checked_at, "reason": "credential_not_configured"}
    request = Request(provider.endpoint, headers=_headers(provider))
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return {"provider": code, "status": "ok", "checked_at": checked_at, "http_status": response.status, "payload_bytes": len(payload), "sha256": _digest(payload)}
    except HTTPError as exc:
        return {"provider": code, "status": "error", "checked_at": checked_at, "http_status": exc.code, "error_type": "http_error"}
    except (URLError, TimeoutError, OSError):
        return {"provider": code, "status": "error", "checked_at": checked_at, "error_type": "network_error"}


def poll_all(*, persist: bool = False) -> dict[str, Any]:
    results = [poll_provider(code) for code in PROVIDERS]
    snapshot = {"schema_version": "1.0.0", "generated_at": datetime.now(timezone.utc).isoformat(), "providers": results}
    if persist:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        previous = {}
        if SNAPSHOT_PATH.exists():
            try:
                previous = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
        previous_hashes = {item.get("provider"): item.get("sha256") for item in previous.get("providers", [])}
        snapshot["deltas"] = [{"provider": item["provider"], "changed": bool(item.get("sha256") and item.get("sha256") != previous_hashes.get(item["provider"]))} for item in results]
        SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return snapshot
