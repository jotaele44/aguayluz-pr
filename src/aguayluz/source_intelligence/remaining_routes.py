"""Terminal discovery-surface governance for every bounded source family.

A family discovery surface is not a data payload product. It proves that the family
itself has one governed discovery entrypoint while payload-bearing products are
registered separately only when their identity and canonical acquisition route are
independently verified.
"""
from __future__ import annotations

from .catalog import SOURCE_FAMILIES
from .routes import (
    AcquisitionRouteDefinition,
    ProductIdentityState,
    ProductPayloadState,
    RepresentationType,
    RouteRole,
    SourceProductDefinition,
    validate_route_registry,
)


def _product_id(source_family_id: str) -> str:
    return f"{source_family_id}_FAMILY_DISCOVERY"


def _route_id(source_family_id: str) -> str:
    return f"{source_family_id}_FAMILY_DISCOVERY_ROUTE"


REMAINING_SOURCE_PRODUCTS = tuple(
    SourceProductDefinition(
        product_id=_product_id(source.source_family_id),
        source_family_id=source.source_family_id,
        label=f"{source.label} — governed family discovery surface",
        origin_authority=source.authority,
        distributor=source.authority,
        native_dataset_id=f"{source.source_family_id}:DISCOVERY_SURFACE",
        spatial_scope="DECLARED_SOURCE_FAMILY_SCOPE",
        temporal_scope="AS_PUBLISHED",
        identity_state=ProductIdentityState.VERIFIED,
        payload_state=ProductPayloadState.DISCOVERY_ONLY,
        canonical_discovery_route_id=_route_id(source.source_family_id),
        canonical_payload_route_id=None,
    )
    for source in SOURCE_FAMILIES
)

REMAINING_ACQUISITION_ROUTES = tuple(
    AcquisitionRouteDefinition(
        route_id=_route_id(source.source_family_id),
        product_id=_product_id(source.source_family_id),
        role=RouteRole.DISCOVERY,
        representation=RepresentationType.CATALOG,
        locator=source.canonical_locator,
        priority=1,
    )
    for source in SOURCE_FAMILIES
)

validate_route_registry(REMAINING_SOURCE_PRODUCTS, REMAINING_ACQUISITION_ROUTES)
