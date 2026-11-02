"""Acquisition-route registry for U.S. EIA source products."""
from __future__ import annotations

from .routes import (
    AcquisitionRouteDefinition,
    RepresentationType,
    RouteRole,
    SourceProductDefinition,
    validate_route_registry,
)

EIA_SOURCE_PRODUCTS = (
    SourceProductDefinition(
        product_id="EIA_860M_MONTHLY_GENERATOR",
        source_family_id="EIA_860M",
        label="EIA-860M monthly generator inventory",
        origin_authority="U.S. EIA",
        distributor="U.S. EIA",
        native_dataset_id="EIA-860M",
        spatial_scope="UNITED_STATES_AND_TERRITORIES",
        temporal_scope="MONTHLY",
        canonical_discovery_route_id="EIA_860M_INDEX",
        canonical_payload_route_id="EIA_860M_MONTHLY_XLSX",
    ),
    SourceProductDefinition(
        product_id="EIA_923_ANNUAL_PACKAGE",
        source_family_id="EIA_923",
        label="EIA-923 current-year generation and fuel package",
        origin_authority="U.S. EIA",
        distributor="U.S. EIA",
        native_dataset_id="EIA-923",
        spatial_scope="UNITED_STATES_AND_TERRITORIES",
        temporal_scope="CURRENT_YEAR_MONTHLY_RELEASES",
        canonical_discovery_route_id="EIA_923_INDEX",
        canonical_payload_route_id="EIA_923_CURRENT_YEAR_ZIP",
    ),
)

EIA_ACQUISITION_ROUTES = (
    AcquisitionRouteDefinition(
        route_id="EIA_860M_INDEX",
        product_id="EIA_860M_MONTHLY_GENERATOR",
        role=RouteRole.DISCOVERY,
        representation=RepresentationType.CATALOG,
        locator="https://www.eia.gov/electricity/data/eia860m/",
        priority=1,
    ),
    AcquisitionRouteDefinition(
        route_id="EIA_860M_MONTHLY_XLSX",
        product_id="EIA_860M_MONTHLY_GENERATOR",
        role=RouteRole.CANONICAL_PAYLOAD,
        representation=RepresentationType.FULL_PAYLOAD,
        locator="https://www.eia.gov/electricity/data/eia860m/archive/xls/{month}_generator{year}.xlsx",
        priority=1,
        lossless=True,
        may_publish_canonical=True,
    ),
    AcquisitionRouteDefinition(
        route_id="EIA_923_INDEX",
        product_id="EIA_923_ANNUAL_PACKAGE",
        role=RouteRole.DISCOVERY,
        representation=RepresentationType.CATALOG,
        locator="https://www.eia.gov/electricity/data/eia923/",
        priority=1,
    ),
    AcquisitionRouteDefinition(
        route_id="EIA_923_CURRENT_YEAR_ZIP",
        product_id="EIA_923_ANNUAL_PACKAGE",
        role=RouteRole.CANONICAL_PAYLOAD,
        representation=RepresentationType.FULL_PAYLOAD,
        locator="https://www.eia.gov/electricity/data/eia923/xls/f923_{year}.zip",
        priority=1,
        lossless=True,
        may_publish_canonical=True,
    ),
)

validate_route_registry(EIA_SOURCE_PRODUCTS, EIA_ACQUISITION_ROUTES)
