"""Verified USGS geospatial acquisition routes for 3DEP and 3DHP."""
from __future__ import annotations

from .routes import (
    AcquisitionRouteDefinition,
    RepresentationType,
    RouteRole,
    SourceProductDefinition,
    validate_route_registry,
)

VERIFIED_GEOSPATIAL_PRODUCTS = (
    SourceProductDefinition(
        product_id="USGS_3DEP_TNMACCESS_PRODUCTS",
        source_family_id="USGS_3DEP",
        label="The National Map downloadable 3DEP product catalog",
        origin_authority="USGS",
        distributor="The National Map",
        native_dataset_id="TNMAccess/products",
        spatial_scope="UNITED_STATES_AND_TERRITORIES",
        temporal_scope="CURRENT_CATALOG",
        canonical_discovery_route_id="USGS_3DEP_TNMACCESS_DISCOVERY",
        canonical_payload_route_id="USGS_3DEP_TNMACCESS_PRODUCTS_API",
    ),
    SourceProductDefinition(
        product_id="USGS_3DHP_FEATURE_SERVICE",
        source_family_id="USGS_HYDROGRAPHY",
        label="USGS 3D Hydrography Program all-features service",
        origin_authority="USGS",
        distributor="3D Hydrography Program",
        native_dataset_id="usgs_3dhp_all",
        spatial_scope="UNITED_STATES_AND_TERRITORIES",
        temporal_scope="QUARTERLY_SERVICE_UPDATES",
        canonical_discovery_route_id="USGS_3DHP_SERVICE_DISCOVERY",
        canonical_payload_route_id="USGS_3DHP_FEATURESERVER",
    ),
)

VERIFIED_GEOSPATIAL_ROUTES = (
    AcquisitionRouteDefinition(
        route_id="USGS_3DEP_TNMACCESS_DISCOVERY",
        product_id="USGS_3DEP_TNMACCESS_PRODUCTS",
        role=RouteRole.DISCOVERY,
        representation=RepresentationType.CATALOG,
        locator="https://tnmaccess.nationalmap.gov/api/v1/docs",
        priority=1,
    ),
    AcquisitionRouteDefinition(
        route_id="USGS_3DEP_TNMACCESS_PRODUCTS_API",
        product_id="USGS_3DEP_TNMACCESS_PRODUCTS",
        role=RouteRole.CANONICAL_PAYLOAD,
        representation=RepresentationType.FULL_PAYLOAD,
        locator="https://tnmaccess.nationalmap.gov/api/v1/products",
        priority=1,
        lossless=True,
        may_publish_canonical=True,
    ),
    AcquisitionRouteDefinition(
        route_id="USGS_3DHP_SERVICE_DISCOVERY",
        product_id="USGS_3DHP_FEATURE_SERVICE",
        role=RouteRole.DISCOVERY,
        representation=RepresentationType.CATALOG,
        locator="https://www.usgs.gov/3d-hydrography-program/access-3dhp-data-products",
        priority=1,
    ),
    AcquisitionRouteDefinition(
        route_id="USGS_3DHP_FEATURESERVER",
        product_id="USGS_3DHP_FEATURE_SERVICE",
        role=RouteRole.CANONICAL_PAYLOAD,
        representation=RepresentationType.FULL_PAYLOAD,
        locator="https://3dhp.nationalmap.gov/arcgis/rest/services/usgs_3dhp_all/FeatureServer",
        priority=1,
        lossless=True,
        may_publish_canonical=True,
    ),
)

validate_route_registry(VERIFIED_GEOSPATIAL_PRODUCTS, VERIFIED_GEOSPATIAL_ROUTES)
