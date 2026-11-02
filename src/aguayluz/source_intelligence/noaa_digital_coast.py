"""Source products and acquisition routes for NOAA Digital Coast elevation."""
from __future__ import annotations

from .routes import (
    AcquisitionRouteDefinition,
    RepresentationType,
    RouteRole,
    SourceProductDefinition,
    validate_route_registry,
)

NOAA_DIGITAL_COAST_PRODUCTS = (
    SourceProductDefinition(
        product_id="NOAA_DC_LIDAR_8630",
        source_family_id="NOAA_DIGITAL_COAST_ELEVATION",
        label="2015-2017 USGS Lidar: Puerto Rico",
        origin_authority="USGS",
        distributor="NOAA Office for Coastal Management / Digital Coast",
        native_dataset_id="8630",
        spatial_scope="PUERTO_RICO",
        temporal_scope="2015-2017",
        canonical_discovery_route_id="NOAA_DC_8630_STAC",
        canonical_payload_route_id="NOAA_DC_8630_BULK_HTTPS",
    ),
)

NOAA_DIGITAL_COAST_ROUTES = (
    AcquisitionRouteDefinition(
        route_id="NOAA_DC_8630_STAC",
        product_id="NOAA_DC_LIDAR_8630",
        role=RouteRole.DISCOVERY,
        representation=RepresentationType.CATALOG,
        locator="https://coast.noaa.gov/htdata/lidar1_z/",
        priority=1,
    ),
    AcquisitionRouteDefinition(
        route_id="NOAA_DC_8630_BULK_HTTPS",
        product_id="NOAA_DC_LIDAR_8630",
        role=RouteRole.CANONICAL_PAYLOAD,
        representation=RepresentationType.FULL_PAYLOAD,
        locator="https://coast.noaa.gov/htdata/lidar1_z/",
        priority=1,
        lossless=True,
        may_publish_canonical=True,
    ),
    AcquisitionRouteDefinition(
        route_id="NOAA_DC_8630_DAV",
        product_id="NOAA_DC_LIDAR_8630",
        role=RouteRole.DERIVED_SUBSET,
        representation=RepresentationType.SUBSET_PAYLOAD,
        locator="https://coast.noaa.gov/dataviewer/#/lidar/search/where/id/8630/details/8630",
        priority=1,
        subset_capable=True,
    ),
    AcquisitionRouteDefinition(
        route_id="NOAA_DC_8630_EPT",
        product_id="NOAA_DC_LIDAR_8630",
        role=RouteRole.STREAMING_ANALYSIS,
        representation=RepresentationType.STREAM,
        locator="USGS:PR_PuertoRico_2015_2018",
        priority=1,
    ),
    AcquisitionRouteDefinition(
        route_id="NOAA_DC_8630_POTREE",
        product_id="NOAA_DC_LIDAR_8630",
        role=RouteRole.VISUALIZATION_ONLY,
        representation=RepresentationType.VIEWER,
        locator="USGS Potree viewer for PR_PuertoRico_2015_2018",
        priority=1,
        verification_only=True,
    ),
    AcquisitionRouteDefinition(
        route_id="NOAA_DC_8630_TILE_INDEX",
        product_id="NOAA_DC_LIDAR_8630",
        role=RouteRole.COVERAGE_VERIFICATION,
        representation=RepresentationType.TILE_INDEX,
        locator="NOAA Digital Coast dataset 8630 tile index",
        priority=1,
        verification_only=True,
    ),
    AcquisitionRouteDefinition(
        route_id="NOAA_DC_8630_METADATA",
        product_id="NOAA_DC_LIDAR_8630",
        role=RouteRole.METADATA,
        representation=RepresentationType.METADATA,
        locator="NOAA Digital Coast dataset 8630 ISO/InPort metadata",
        priority=1,
        verification_only=True,
    ),
    AcquisitionRouteDefinition(
        route_id="NOAA_DC_8630_REPORTS",
        product_id="NOAA_DC_LIDAR_8630",
        role=RouteRole.REPORTS,
        representation=RepresentationType.REPORT,
        locator="NOAA Digital Coast dataset 8630 survey/checkpoint/project reports",
        priority=1,
        verification_only=True,
    ),
)

validate_route_registry(NOAA_DIGITAL_COAST_PRODUCTS, NOAA_DIGITAL_COAST_ROUTES)
