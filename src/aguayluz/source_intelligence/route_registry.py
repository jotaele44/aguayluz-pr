"""Aggregate source-product and acquisition-route registry."""
from __future__ import annotations

from .eia_routes import EIA_ACQUISITION_ROUTES, EIA_SOURCE_PRODUCTS
from .noaa_digital_coast import NOAA_DIGITAL_COAST_PRODUCTS, NOAA_DIGITAL_COAST_ROUTES
from .routes import validate_route_registry

SOURCE_PRODUCTS = EIA_SOURCE_PRODUCTS + NOAA_DIGITAL_COAST_PRODUCTS
ACQUISITION_ROUTES = EIA_ACQUISITION_ROUTES + NOAA_DIGITAL_COAST_ROUTES

validate_route_registry(SOURCE_PRODUCTS, ACQUISITION_ROUTES)
