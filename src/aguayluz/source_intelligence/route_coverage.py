"""Coverage accounting for source-product acquisition-route governance."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .catalog import SOURCE_FAMILIES
from .noaa_digital_coast import NOAA_DIGITAL_COAST_PRODUCTS, NOAA_DIGITAL_COAST_ROUTES
from .routes import RouteRole


class RouteGovernanceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_source_families: int = Field(ge=0)
    governed_source_families: int = Field(ge=0)
    ungoverned_source_family_ids: tuple[str, ...]
    total_products: int = Field(ge=0)
    products_with_single_canonical_payload: int = Field(ge=0)
    products_without_single_canonical_payload: tuple[str, ...]
    zero_redundant_fetches_certifiable: bool


def route_governance_summary() -> RouteGovernanceSummary:
    products = NOAA_DIGITAL_COAST_PRODUCTS
    routes = NOAA_DIGITAL_COAST_ROUTES

    governed_families = {product.source_family_id for product in products}
    all_families = {source.source_family_id for source in SOURCE_FAMILIES}
    ungoverned = tuple(sorted(all_families - governed_families))

    missing: list[str] = []
    for product in products:
        canonical = [
            route
            for route in routes
            if route.product_id == product.product_id
            and route.role == RouteRole.CANONICAL_PAYLOAD
        ]
        if len(canonical) != 1:
            missing.append(product.product_id)

    return RouteGovernanceSummary(
        total_source_families=len(all_families),
        governed_source_families=len(governed_families),
        ungoverned_source_family_ids=ungoverned,
        total_products=len(products),
        products_with_single_canonical_payload=len(products) - len(missing),
        products_without_single_canonical_payload=tuple(sorted(missing)),
        zero_redundant_fetches_certifiable=not ungoverned and not missing,
    )
