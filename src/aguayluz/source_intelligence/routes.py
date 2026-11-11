"""Canonical source-product and acquisition-route governance.

A source product may be exposed through several network/access routes. Routes are not
independent source identity. Exactly one route may be canonical for full-payload
acquisition; alternates are discovery, fallback, subset, streaming, visualization, or
verification-only paths.
"""
from __future__ import annotations

from collections import Counter
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RouteRole(str, Enum):
    DISCOVERY = "DISCOVERY"
    CANONICAL_PAYLOAD = "CANONICAL_PAYLOAD"
    FALLBACK_PAYLOAD = "FALLBACK_PAYLOAD"
    DERIVED_SUBSET = "DERIVED_SUBSET"
    STREAMING_ANALYSIS = "STREAMING_ANALYSIS"
    VISUALIZATION_ONLY = "VISUALIZATION_ONLY"
    COVERAGE_VERIFICATION = "COVERAGE_VERIFICATION"
    METADATA = "METADATA"
    REPORTS = "REPORTS"


class RepresentationType(str, Enum):
    CATALOG = "CATALOG"
    METADATA = "METADATA"
    FULL_PAYLOAD = "FULL_PAYLOAD"
    SUBSET_PAYLOAD = "SUBSET_PAYLOAD"
    STREAM = "STREAM"
    VIEWER = "VIEWER"
    FOOTPRINT = "FOOTPRINT"
    TILE_INDEX = "TILE_INDEX"
    REPORT = "REPORT"


class PayloadIdentityClass(str, Enum):
    BYTE_IDENTICAL = "BYTE_IDENTICAL"
    PURE_RECOMPRESSION = "PURE_RECOMPRESSION"
    SAME_PAYLOADS_DIFFERENT_PATHS = "SAME_PAYLOADS_DIFFERENT_PATHS"
    DISTINCT_PAYLOADS = "DISTINCT_PAYLOADS"
    UNRESOLVED = "UNRESOLVED"


class ProductIdentityState(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    UNRESOLVED = "UNRESOLVED"


class ProductPayloadState(str, Enum):
    CANONICAL_ROUTE = "CANONICAL_ROUTE"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    NO_PUBLIC_PAYLOAD = "NO_PUBLIC_PAYLOAD"
    UNRESOLVED = "UNRESOLVED"


class FetchPurpose(str, Enum):
    DISCOVER = "DISCOVER"
    FULL_PAYLOAD = "FULL_PAYLOAD"
    SUBSET = "SUBSET"
    STREAM = "STREAM"
    VISUALIZE = "VISUALIZE"
    VERIFY_COVERAGE = "VERIFY_COVERAGE"
    METADATA = "METADATA"
    REPORTS = "REPORTS"


class FetchAction(str, Enum):
    FETCH = "FETCH"
    SKIP_USE_EXISTING = "SKIP_USE_EXISTING"
    BLOCKED = "BLOCKED"


class SourceProductDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    source_family_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    label: str = Field(min_length=1)
    origin_authority: str = Field(min_length=1)
    distributor: str = Field(min_length=1)
    native_dataset_id: str = Field(min_length=1)
    spatial_scope: str = Field(min_length=1)
    temporal_scope: str = Field(min_length=1)
    identity_state: ProductIdentityState = ProductIdentityState.VERIFIED
    payload_state: ProductPayloadState = ProductPayloadState.CANONICAL_ROUTE
    canonical_discovery_route_id: str
    canonical_payload_route_id: str | None = None


class AcquisitionRouteDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    product_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    role: RouteRole
    representation: RepresentationType
    locator: str = Field(min_length=1)
    priority: int = Field(ge=1)
    lossless: bool | None = None
    subset_capable: bool = False
    verification_only: bool = False
    may_publish_canonical: bool = False

    @model_validator(mode="after")
    def canonical_payload_constraints(self) -> AcquisitionRouteDefinition:
        if self.role == RouteRole.CANONICAL_PAYLOAD:
            if self.representation != RepresentationType.FULL_PAYLOAD:
                raise ValueError("canonical payload route must be FULL_PAYLOAD")
            if not self.may_publish_canonical:
                raise ValueError("canonical payload route must permit canonical publication")
            if self.verification_only:
                raise ValueError("canonical payload route cannot be verification-only")
        elif self.may_publish_canonical:
            raise ValueError("only CANONICAL_PAYLOAD may publish canonical data")
        return self


class ArchiveMemberDigest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    uncompressed_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FetchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str
    purpose: FetchPurpose
    action: FetchAction
    route_id: str | None
    reason: str


def validate_route_registry(
    products: tuple[SourceProductDefinition, ...],
    routes: tuple[AcquisitionRouteDefinition, ...],
) -> None:
    product_ids = [p.product_id for p in products]
    route_ids = [r.route_id for r in routes]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("duplicate source product ID")
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("duplicate acquisition route ID")

    product_set = set(product_ids)
    routes_by_product: dict[str, list[AcquisitionRouteDefinition]] = {}
    for route in routes:
        if route.product_id not in product_set:
            raise ValueError(f"route references unknown product {route.product_id}")
        routes_by_product.setdefault(route.product_id, []).append(route)

    for product in products:
        owned = routes_by_product.get(product.product_id, [])
        canonical_payload = [r for r in owned if r.role == RouteRole.CANONICAL_PAYLOAD]
        by_id = {r.route_id: r for r in owned}
        if product.canonical_discovery_route_id not in by_id:
            raise ValueError(f"{product.product_id} canonical discovery route missing")
        if by_id[product.canonical_discovery_route_id].role != RouteRole.DISCOVERY:
            raise ValueError("canonical_discovery_route_id does not point at DISCOVERY")
        if product.payload_state == ProductPayloadState.CANONICAL_ROUTE:
            if len(canonical_payload) != 1:
                raise ValueError(
                    f"{product.product_id} must have exactly one canonical payload route"
                )
            if product.canonical_payload_route_id not in by_id:
                raise ValueError(f"{product.product_id} canonical payload route missing")
            if by_id[product.canonical_payload_route_id].role != RouteRole.CANONICAL_PAYLOAD:
                raise ValueError(
                    "canonical_payload_route_id does not point at CANONICAL_PAYLOAD"
                )
        else:
            if canonical_payload:
                raise ValueError(
                    f"{product.product_id} cannot declare CANONICAL_PAYLOAD while "
                    f"payload_state={product.payload_state.value}"
                )
            if product.canonical_payload_route_id is not None:
                raise ValueError(
                    f"{product.product_id} canonical_payload_route_id must be null "
                    f"when payload_state={product.payload_state.value}"
                )


def _purpose_roles(purpose: FetchPurpose) -> tuple[RouteRole, ...]:
    return {
        FetchPurpose.DISCOVER: (RouteRole.DISCOVERY,),
        FetchPurpose.FULL_PAYLOAD: (
            RouteRole.CANONICAL_PAYLOAD,
            RouteRole.FALLBACK_PAYLOAD,
        ),
        FetchPurpose.SUBSET: (RouteRole.DERIVED_SUBSET,),
        FetchPurpose.STREAM: (RouteRole.STREAMING_ANALYSIS,),
        FetchPurpose.VISUALIZE: (RouteRole.VISUALIZATION_ONLY,),
        FetchPurpose.VERIFY_COVERAGE: (RouteRole.COVERAGE_VERIFICATION,),
        FetchPurpose.METADATA: (RouteRole.METADATA,),
        FetchPurpose.REPORTS: (RouteRole.REPORTS,),
    }[purpose]


def resolve_route(
    product_id: str,
    purpose: FetchPurpose,
    *,
    products: tuple[SourceProductDefinition, ...],
    routes: tuple[AcquisitionRouteDefinition, ...],
    unavailable_route_ids: set[str] | None = None,
) -> AcquisitionRouteDefinition:
    unavailable = unavailable_route_ids or set()
    product = next((p for p in products if p.product_id == product_id), None)
    if product is None:
        raise ValueError(f"unknown source product {product_id}")
    if (
        purpose == FetchPurpose.FULL_PAYLOAD
        and product.payload_state != ProductPayloadState.CANONICAL_ROUTE
    ):
        raise ValueError(
            f"full payload route unresolved for {product_id}: "
            f"{product.payload_state.value}"
        )
    candidates = [
        r
        for r in routes
        if r.product_id == product_id
        and r.role in _purpose_roles(purpose)
        and r.route_id not in unavailable
    ]
    if purpose == FetchPurpose.FULL_PAYLOAD:
        candidates.sort(
            key=lambda r: (
                r.role != RouteRole.CANONICAL_PAYLOAD,
                r.priority,
                r.route_id,
            )
        )
    else:
        candidates.sort(key=lambda r: (r.priority, r.route_id))
    if not candidates:
        raise ValueError(f"no available route for {product_id} purpose={purpose.value}")
    return candidates[0]


def fetch_decision(
    product_id: str,
    purpose: FetchPurpose,
    *,
    products: tuple[SourceProductDefinition, ...],
    routes: tuple[AcquisitionRouteDefinition, ...],
    existing_representation_route_ids: set[str] | None = None,
    unavailable_route_ids: set[str] | None = None,
) -> FetchDecision:
    existing = existing_representation_route_ids or set()
    route = resolve_route(
        product_id,
        purpose,
        products=products,
        routes=routes,
        unavailable_route_ids=unavailable_route_ids,
    )
    if route.route_id in existing:
        return FetchDecision(
            product_id=product_id,
            purpose=purpose,
            action=FetchAction.SKIP_USE_EXISTING,
            route_id=route.route_id,
            reason="required representation already frozen from selected route",
        )
    return FetchDecision(
        product_id=product_id,
        purpose=purpose,
        action=FetchAction.FETCH,
        route_id=route.route_id,
        reason="selected deterministic route for requested representation",
    )


def classify_archive_identity(
    a_outer_sha256: str,
    a_members: tuple[ArchiveMemberDigest, ...],
    b_outer_sha256: str,
    b_members: tuple[ArchiveMemberDigest, ...],
) -> PayloadIdentityClass:
    if a_outer_sha256 == b_outer_sha256:
        return PayloadIdentityClass.BYTE_IDENTICAL

    a_by_path = {
        member.path: (member.uncompressed_size, member.sha256) for member in a_members
    }
    b_by_path = {
        member.path: (member.uncompressed_size, member.sha256) for member in b_members
    }
    if a_by_path == b_by_path and a_by_path:
        return PayloadIdentityClass.PURE_RECOMPRESSION

    a_payloads = Counter(
        (member.uncompressed_size, member.sha256) for member in a_members
    )
    b_payloads = Counter(
        (member.uncompressed_size, member.sha256) for member in b_members
    )
    if a_payloads == b_payloads and a_payloads:
        return PayloadIdentityClass.SAME_PAYLOADS_DIFFERENT_PATHS

    if a_members and b_members:
        return PayloadIdentityClass.DISTINCT_PAYLOADS
    return PayloadIdentityClass.UNRESOLVED
