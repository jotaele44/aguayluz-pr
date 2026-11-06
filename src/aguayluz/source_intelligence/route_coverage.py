"""Coverage accounting for source-product acquisition-route governance."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .catalog import SOURCE_FAMILIES
from .route_registry import ACQUISITION_ROUTES, SOURCE_PRODUCTS
from .routes import ProductIdentityState, ProductPayloadState, RouteRole

# A governed discovery surface proves that the source family is represented in the
# control plane. It does not prove that every payload-bearing product exposed by that
# family has been discovered. Keep payload-product denominator exhaustion explicit and
# fail-closed. These two EIA families are bounded to the registered public products.
PAYLOAD_PRODUCT_DENOMINATOR_EXHAUSTED_FAMILY_IDS = frozenset(
    {
        "EIA_860M",
        "EIA_923",
    }
)


class RouteGovernanceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_source_families: int = Field(ge=0)
    governed_source_families: int = Field(ge=0)
    ungoverned_source_family_ids: tuple[str, ...]
    route_governance_coverage_percent: float = Field(ge=0, le=100)
    route_governance_coverage_complete: bool

    total_products: int = Field(ge=0)
    verified_product_identity_count: int = Field(ge=0)
    provisional_or_unresolved_product_ids: tuple[str, ...]
    products_with_canonical_payload: int = Field(ge=0)
    products_without_resolved_payload_ids: tuple[str, ...]
    products_with_invalid_canonical_payload_count: int = Field(ge=0)

    payload_product_denominator_exhausted_family_ids: tuple[str, ...]
    open_payload_product_denominator_family_ids: tuple[str, ...]
    payload_product_denominator_complete: bool

    zero_redundant_fetches_within_registered_products: bool
    zero_redundant_fetches_certifiable: bool


def route_governance_summary() -> RouteGovernanceSummary:
    products = SOURCE_PRODUCTS
    routes = ACQUISITION_ROUTES

    governed_families = {product.source_family_id for product in products}
    all_families = {source.source_family_id for source in SOURCE_FAMILIES}
    ungoverned = tuple(sorted(all_families - governed_families))
    covered = len(governed_families & all_families)
    coverage_percent = 100.0 if not all_families else round(
        100.0 * covered / len(all_families),
        2,
    )
    coverage_complete = not ungoverned and governed_families >= all_families

    identity_blockers = tuple(
        sorted(
            product.product_id
            for product in products
            if product.identity_state != ProductIdentityState.VERIFIED
        )
    )
    payload_blockers = tuple(
        sorted(
            product.product_id
            for product in products
            if product.payload_state == ProductPayloadState.UNRESOLVED
        )
    )

    canonical_count = 0
    invalid_canonical_count = 0
    for product in products:
        canonical = [
            route
            for route in routes
            if route.product_id == product.product_id
            and route.role == RouteRole.CANONICAL_PAYLOAD
        ]
        if product.payload_state == ProductPayloadState.CANONICAL_ROUTE:
            if len(canonical) == 1:
                canonical_count += 1
            else:
                invalid_canonical_count += 1
        elif canonical:
            invalid_canonical_count += 1

    exhausted_families = tuple(
        sorted(all_families & PAYLOAD_PRODUCT_DENOMINATOR_EXHAUSTED_FAMILY_IDS)
    )
    open_denominators = tuple(
        sorted(all_families - PAYLOAD_PRODUCT_DENOMINATOR_EXHAUSTED_FAMILY_IDS)
    )
    denominator_complete = not open_denominators

    registered_products_clean = (
        coverage_complete
        and not identity_blockers
        and not payload_blockers
        and invalid_canonical_count == 0
    )
    zero_redundant_certifiable = (
        registered_products_clean
        and denominator_complete
    )

    return RouteGovernanceSummary(
        total_source_families=len(all_families),
        governed_source_families=covered,
        ungoverned_source_family_ids=ungoverned,
        route_governance_coverage_percent=coverage_percent,
        route_governance_coverage_complete=coverage_complete,
        total_products=len(products),
        verified_product_identity_count=len(products) - len(identity_blockers),
        provisional_or_unresolved_product_ids=identity_blockers,
        products_with_canonical_payload=canonical_count,
        products_without_resolved_payload_ids=payload_blockers,
        products_with_invalid_canonical_payload_count=invalid_canonical_count,
        payload_product_denominator_exhausted_family_ids=exhausted_families,
        open_payload_product_denominator_family_ids=open_denominators,
        payload_product_denominator_complete=denominator_complete,
        zero_redundant_fetches_within_registered_products=registered_products_clean,
        zero_redundant_fetches_certifiable=zero_redundant_certifiable,
    )
