"""HTTP client for HIFLD ArcGIS FeatureServer layers.

Public access via ArcGIS REST query endpoints. URL pattern:
  https://services1.arcgis.com/<org-id>/ArcGIS/rest/services/<layer>/FeatureServer/0/query
        ?where=<sql>&outFields=*&f=geojson&outSR=4326

HIFLD hub URLs are historically inconsistent over plain HTTP fetches (404s
intermittently), so this client uses a try-live-then-snapshot fallback —
configurable per layer — and logs a warning when falling back.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("aguayluz.ingest.hifld_client")

DEFAULT_TIMEOUT_S = 30.0
USER_AGENT = "aguayluz-pr/0.1 (+https://github.com/jotaele44/aguayluz-pr)"

# Known HIFLD ArcGIS FeatureServer URLs (subject to drift; fallback covers).
LAYER_URLS = {
    "electric_substations": (
        "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/ArcGIS/rest/services/"
        "Electric_Substations/FeatureServer/0/query"
    ),
    "wastewater_treatment_plants": (
        "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/ArcGIS/rest/services/"
        "Wastewater_Treatment_Plants/FeatureServer/0/query"
    ),
    "public_water_supply_systems": (
        "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/ArcGIS/rest/services/"
        "Public_Water_Supply_Service_Areas/FeatureServer/0/query"
    ),
}


class HIFLDClientError(Exception):
    """Raised on non-retryable HIFLD API failures (4xx other than 429)."""


def _live_query_params(state: str, max_features: int) -> dict[str, str]:
    return {
        "where": f"STATE='{state}'",
        "outFields": "*",
        "f": "geojson",
        "outSR": "4326",
        "resultRecordCount": str(max_features),
    }


def fetch_layer(
    *,
    layer: str,
    state: str = "PR",
    max_features: int = 500,
    fallback_path: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch a HIFLD layer as GeoJSON, falling back to a committed snapshot.

    `layer` selects from `LAYER_URLS`. `fallback_path` should point at a
    committed `.geojson` snapshot in `tests/fixtures/hifld/`; when the live
    URL 404s or times out we load it and log a warning instead of raising.
    Pass `fallback_path=None` to disable fallback (raises on live failure).
    """
    url = LAYER_URLS.get(layer)
    if url is None:
        raise HIFLDClientError(f"unknown layer {layer!r}; known: {sorted(LAYER_URLS)}")

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
    try:
        try:
            response = client.get(url, params=_live_query_params(state, max_features))
            if response.status_code == 200:
                payload = response.json()
                # Some ArcGIS errors come back as HTTP 200 with `{"error": ...}`.
                if isinstance(payload, dict) and payload.get("error"):
                    raise HIFLDClientError(f"HIFLD service error: {payload['error']}")
                return payload
            raise HIFLDClientError(f"HIFLD HTTP {response.status_code} for layer={layer}")
        except (httpx.HTTPError, HIFLDClientError) as exc:
            if fallback_path is None:
                raise
            logger.warning("HIFLD live fetch failed (%s); falling back to %s", exc, fallback_path)
            return _load_fallback(fallback_path)
    finally:
        if owns_client:
            client.close()


def _load_fallback(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HIFLDClientError(f"HIFLD fallback snapshot missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_layers(
    *,
    layers: Iterable[str],
    state: str = "PR",
    max_features: int = 500,
    fallback_paths: dict[str, Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """Convenience: fetch multiple layers, return `{layer_name: geojson_envelope}`."""
    fallback_paths = fallback_paths or {}
    out: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=DEFAULT_TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as client:
        for layer in layers:
            out[layer] = fetch_layer(
                layer=layer,
                state=state,
                max_features=max_features,
                fallback_path=fallback_paths.get(layer),
                client=client,
            )
    return out
