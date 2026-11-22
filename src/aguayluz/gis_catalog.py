"""Build the gis-layer-catalog/1.0 document served at ``GET /gis/catalog``.

Source of truth: ``config/gis_layer_catalog.yaml``. The contract is
``schemas/gis_layer_catalog_v1.schema.json``, mirrored from spiderweb-pr.
Pure: the caller loads the YAML and supplies a ``data_available`` probe.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

CONTRACT_CATALOG = "gis-layer-catalog/1.0"
PRODUCER_REPO = "aguayluz-pr"
GENERATED_FROM = ("config/gis_layer_catalog.yaml",)

_NULLABLE_FIELDS = (
    "group",
    "blocked_reason",
    "min_zoom",
    "max_zoom",
    "temporal_field",
    "classification",
    "classification_blocked_reason",
    "precision_field",
    "precision_max_zoom",
    "documents_ref",
    "network_ref",
    "federation_layer_id",
)


class GisCatalogError(ValueError):
    """The catalog config is malformed (duplicate or missing layer ids)."""


def build_gis_catalog(
    config: Mapping[str, Any],
    *,
    data_available: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    defaults = config.get("defaults") or {}
    layers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in config.get("layers") or []:
        layer_id = raw.get("layer_id")
        if not isinstance(layer_id, str) or not layer_id:
            raise GisCatalogError("every catalog layer needs a layer_id")
        if layer_id in seen:
            raise GisCatalogError(f"duplicate layer_id {layer_id!r}")
        seen.add(layer_id)
        access = raw.get("access_default", defaults.get("access_default"))
        source = raw.get("source") or {"kind": "none", "url": None}
        entry: dict[str, Any] = {
            "layer_id": layer_id,
            "title": raw.get("title") or layer_id,
            "category": raw.get("category") or "Uncategorised",
            "visibility_class": raw.get("visibility_class"),
            "access_default": access,
            "status": raw.get("status", defaults.get("status", "active")),
            "source": {
                "kind": source.get("kind", "none"),
                "url": source.get("url"),
                "source_layer": source.get("source_layer"),
            },
            "geometry_types": list(raw.get("geometry_types") or []),
            "default_visible": bool(raw.get("default_visible", False)),
            "identify_fields": list(raw.get("identify_fields") or []),
            "search_fields": list(raw.get("search_fields") or []),
            "query_modes": list(
                raw["query_modes"] if "query_modes" in raw else defaults.get("query_modes") or []
            ),
            "exportable": access == "PUBLIC" and raw.get("status", "active") != "blocked",
        }
        for field in _NULLABLE_FIELDS:
            value = raw.get(field)
            entry[field] = value.strip() if isinstance(value, str) else value
        if data_available is not None:
            entry["data_available"] = bool(data_available(layer_id))
        layers.append(entry)
    return {
        "contract_version": CONTRACT_CATALOG,
        "producer_repo": PRODUCER_REPO,
        "generated_from": list(GENERATED_FROM),
        "layers": layers,
    }
