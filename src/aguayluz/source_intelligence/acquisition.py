"""Route-aware immutable acquisition admission.

This module is the single canonical-ingestion boundary. It binds exact source bytes to
one verified source product and its declared canonical payload route. Alternate,
subset, streaming, visualization, and verification routes cannot publish canonical
source manifestations.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .adapters.base import RawArtifact
from .route_registry import ACQUISITION_ROUTES, SOURCE_PRODUCTS
from .routes import (
    FetchPurpose,
    ProductIdentityState,
    ProductPayloadState,
    RouteRole,
    resolve_route,
)
from .runtime import (
    SourceManifestation,
    canonical_json_bytes,
    persist_source_manifestation,
    verify_source_manifestation,
)

RECEIPT_SCHEMA = "aguayluz.source-route-acquisition/v1"


class RouteAcquisitionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = RECEIPT_SCHEMA
    product_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    route_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    source_family_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    manifestation_id: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at_utc: str = Field(min_length=1)


def _product(product_id: str):
    product = next((item for item in SOURCE_PRODUCTS if item.product_id == product_id), None)
    if product is None:
        raise ValueError(f"unknown source product {product_id}")
    return product


def _route(route_id: str):
    route = next((item for item in ACQUISITION_ROUTES if item.route_id == route_id), None)
    if route is None:
        raise ValueError(f"unknown acquisition route {route_id}")
    return route


def canonical_route(product_id: str):
    return resolve_route(
        product_id,
        FetchPurpose.FULL_PAYLOAD,
        products=SOURCE_PRODUCTS,
        routes=ACQUISITION_ROUTES,
    )


def _receipt_path(root: Path, receipt: RouteAcquisitionReceipt) -> Path:
    return (
        root
        / "route_receipts"
        / receipt.product_id
        / f"{receipt.manifestation_id}.json"
    )


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"route receipt collision at immutable path: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError(f"concurrent route receipt collision: {path}") from None


def load_route_receipts(root: Path, product_id: str) -> list[RouteAcquisitionReceipt]:
    folder = root / "route_receipts" / product_id
    if not folder.is_dir():
        return []
    rows: list[RouteAcquisitionReceipt] = []
    for path in sorted(folder.glob("*.json")):
        rows.append(RouteAcquisitionReceipt.model_validate_json(path.read_text(encoding="utf-8")))
    return rows


def canonical_payload_already_frozen(
    root: Path,
    product_id: str,
    byte_sha256: str,
) -> bool:
    return any(
        receipt.byte_sha256 == byte_sha256
        for receipt in load_route_receipts(root, product_id)
    )


def persist_canonical_acquisition(
    root: Path,
    artifact: RawArtifact,
    *,
    product_id: str,
    route_id: str,
    schema_fingerprint: str | None = None,
    record_count: int | None = None,
) -> tuple[SourceManifestation, RouteAcquisitionReceipt]:
    product = _product(product_id)
    route = _route(route_id)

    if product.identity_state != ProductIdentityState.VERIFIED:
        raise ValueError(f"product identity is not verified: {product_id}")
    if product.payload_state != ProductPayloadState.CANONICAL_ROUTE:
        raise ValueError(f"product has no canonical payload route: {product_id}")
    if route.product_id != product_id:
        raise ValueError("route does not belong to requested source product")
    if route.role != RouteRole.CANONICAL_PAYLOAD or not route.may_publish_canonical:
        raise ValueError("only the canonical payload route may publish source bytes")
    if route_id != product.canonical_payload_route_id:
        raise ValueError("route is not the product's canonical payload route")
    if artifact.source_family_id != product.source_family_id:
        raise ValueError("artifact source family does not match source product")

    manifestation = persist_source_manifestation(
        root,
        artifact,
        schema_fingerprint=schema_fingerprint,
        record_count=record_count,
        state="RAW_FROZEN_CANONICAL_ROUTE",
    )
    verify_source_manifestation(root, manifestation)

    receipt = RouteAcquisitionReceipt(
        product_id=product_id,
        route_id=route_id,
        source_family_id=artifact.source_family_id,
        manifestation_id=manifestation.manifestation_id,
        byte_sha256=manifestation.byte_sha256,
        retrieved_at_utc=manifestation.retrieved_at_utc,
    )
    encoded = canonical_json_bytes(receipt.model_dump(mode="json")) + b"\n"
    _write_once(_receipt_path(root, receipt), encoded)
    return manifestation, receipt
