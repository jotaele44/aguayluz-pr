"""Sanitized NEON availability extraction."""
from __future__ import annotations

import json
from typing import Any

from .model import NEON_PRODUCTS, NEON_SITE


def extract_neon_availability(body: bytes) -> dict[str, Any]:
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"site": NEON_SITE, "products": {}, "parse_error": True}
    data = document.get("data", document)
    products = data.get("dataProducts", []) if isinstance(data, dict) else []
    output: dict[str, Any] = {}
    for product in products:
        product_code = str(product.get("dataProductCode", ""))
        if product_code not in NEON_PRODUCTS:
            continue
        output[product_code] = {
            "name": product.get("dataProductTitle") or product.get("dataProductName"),
            "available_months": product.get("availableMonths")
            or product.get("availableDataUrls")
            or [],
        }
    return {"site": NEON_SITE, "products": output, "parse_error": False}
