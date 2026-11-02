"""Governed route placeholders for source families without verified payload routes.

These records close the route-governance denominator without inventing payload URLs.
They are explicitly PROVISIONAL + UNRESOLVED and therefore cannot be selected for a
full-payload fetch or contribute to zero-redundant-fetch certification.
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

_VERIFIED_ROUTE_FAMILIES = {
    "EIA_860M",
    "EIA_923",
    "NOAA_DIGITAL_COAST_ELEVATION",
}


def _product_id(source_family_id: str) -> str:
    return f"{source_family_id}_PRIMARY_PRODUCT"


def _route_id(source_family_id: str) -> str:
    return f"{source_family_id}_DISCOVERY"


_UNRESOLVED_SOURCES = tuple(
    source
    for source in SOURCE_FAMILIES
    if source.source_family_id not in _VERIFIED_ROUTE_FAMILIES
)

REMAINING_SOURCE_PRODUCTS = tuple(
    SourceProductDefinition(
        product_id=_product_id(source.source_family_id),
        source_family_id=source.source_family_id,
        label=f"{source.label} — governed provisional product boundary",
        origin_authority=source.authority,
        distributor=source.authority,
        native_dataset_id=source.source_family_id,
        spatial_scope="DECLARED_SOURCE_FAMILY_SCOPE",
        temporal_scope="AS_PUBLISHED",
        identity_state=ProductIdentityState.PROVISIONAL,
        payload_state=ProductPayloadState.UNRESOLVED,
        canonical_discovery_route_id=_route_id(source.source_family_id),
        canonical_payload_route_id=None,
    )
    for source in _UNRESOLVED_SOURCES
)

REMAINING_ACQUISITION_ROUTES = tuple(
    AcquisitionRouteDefinition(
        route_id=_route_id(source.source_family_id),
        product_id=_product_id(source.source_family_id),
        role=RouteRole.DISCOVERY,
        representation=RepresentationType.CATALOG,
        locator=source.canonical_locator,
        priority=1,
        verification_only=True,
    )
    for source in _UNRESOLVED_SOURCES
)

validate_route_registry(REMAINING_SOURCE_PRODUCTS, REMAINING_ACQUISITION_ROUTES)
