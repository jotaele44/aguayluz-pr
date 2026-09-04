"""Map-manifestation coordinate receipts for AguaYLuz v0.3.

The receipt binds what the operational map displayed and how the coordinate was
obtained. It never lets a display derivation become geometry or feature
identity. Direct, linked-asset, municipality-average, and null states remain
explicitly distinct.
"""
from __future__ import annotations

from enum import StrEnum
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "aguayluz.map-manifestation-receipt.v0.3"
PRODUCER_HEAD = "3678271a03e36375dc3e9f2fb4da0b6b655622bd"
MAP_OWNER = "aguayluz-pr"
DOMAIN_AUTHORITY = "aguayluz-pr"


class ReceiptError(ValueError):
    pass


class CoordinateSource(StrEnum):
    DIRECT = "direct_event_coordinates"
    LINKED_ASSET = "linked_asset"
    MUNICIPALITY_ASSET_AVERAGE = "municipality_asset_average"
    NULL = "null_empty"


class Canonicality(StrEnum):
    SOURCE_NATIVE_NONFEDERATION = "SOURCE_NATIVE_NONFEDERATION"
    DERIVED_REFERENCE_LINK = "DERIVED_REFERENCE_LINK"
    NONCANONICAL_DISPLAY_DERIVATION = "NONCANONICAL_DISPLAY_DERIVATION"
    NULL_EMPTY = "NULL_EMPTY"


class CertificationState(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    AUDIT_ONLY = "AUDIT_ONLY"


_ALLOWED_DIRECT_METHODS = {
    "EXACT", "SURVEYED", "AUTHORITATIVE", "SOURCE_REPORTED",
    "GEOCODED_ROOFTOP", "GEOCODED_PARCEL", "GEOCODED_STREET",
    "GEOCODED_LOCALITY",
}
_ALLOWED_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _valid_point(coords: tuple[float, float] | None) -> bool:
    if coords is None or len(coords) != 2:
        return False
    lon, lat = coords
    return (
        all(math.isfinite(float(value)) for value in coords)
        and -180 <= lon <= 180
        and -90 <= lat <= 90
    )


def build_receipt(
    *,
    event_id: str,
    coordinate_source: CoordinateSource | str,
    coordinates: tuple[float, float] | None,
    geometry_source_ref: str | None = None,
    source_geometry_authority: str | None = None,
    source_coordinate_method: str | None = None,
    source_coordinate_confidence: str | None = None,
    linked_asset_id: str | None = None,
    inherited_geometry_release_pin: Mapping[str, Any] | None = None,
    municipality: str | None = None,
    derivation_asset_ids: Iterable[str] = (),
    producer_head: str = PRODUCER_HEAD,
) -> dict[str, Any]:
    if not event_id.strip():
        raise ReceiptError("event_id is required")
    try:
        source = CoordinateSource(coordinate_source)
    except ValueError as exc:
        raise ReceiptError(f"unknown coordinate_source: {coordinate_source}") from exc

    asset_ids = tuple(
        sorted({str(value).strip() for value in derivation_asset_ids if str(value).strip()})
    )
    geometry: dict[str, Any] | None
    displayed: bool
    failure_reason: str | None = None

    if source is CoordinateSource.NULL:
        if coordinates is not None:
            raise ReceiptError("null_empty receipt must not carry coordinates")
        geometry = None
        displayed = False
        method = "UNKNOWN"
        confidence = "UNKNOWN"
        geometry_authority = None
        canonicality = Canonicality.NULL_EMPTY
        certification = CertificationState.AUDIT_ONLY
        spatial_state = "NULL_EMPTY"
        failure_reason = "NO_VALID_COORDINATE_AVAILABLE"
    else:
        if not _valid_point(coordinates):
            raise ReceiptError(
                "displayed coordinates must be a finite [lon, lat] point in range"
            )
        lon, lat = float(coordinates[0]), float(coordinates[1])
        geometry = {"type": "Point", "coordinates": [lon, lat]}
        displayed = True
        spatial_state = "UNRESOLVED"

        if source is CoordinateSource.DIRECT:
            if not geometry_source_ref:
                raise ReceiptError("direct coordinates require geometry_source_ref")
            method = source_coordinate_method or "SOURCE_REPORTED"
            confidence = source_coordinate_confidence or "UNKNOWN"
            if method not in _ALLOWED_DIRECT_METHODS:
                raise ReceiptError(f"invalid direct coordinate method: {method}")
            if confidence not in _ALLOWED_CONFIDENCE:
                raise ReceiptError(f"invalid coordinate confidence: {confidence}")
            geometry_authority = source_geometry_authority
            canonicality = Canonicality.SOURCE_NATIVE_NONFEDERATION
            certification = (
                CertificationState.PROVISIONAL
                if geometry_authority
                else CertificationState.OPEN
            )

        elif source is CoordinateSource.LINKED_ASSET:
            if not linked_asset_id:
                raise ReceiptError("linked_asset receipt requires linked_asset_id")
            method = "LINKED_ASSET"
            confidence = source_coordinate_confidence or "LOW"
            if confidence not in _ALLOWED_CONFIDENCE:
                raise ReceiptError(f"invalid coordinate confidence: {confidence}")
            geometry_authority = source_geometry_authority
            canonicality = Canonicality.DERIVED_REFERENCE_LINK
            pin = inherited_geometry_release_pin or {}
            exact_pin = bool(
                pin.get("producer_commit_sha")
                and pin.get("release_id")
                and pin.get("logical_geometry_sha256")
            )
            certification = (
                CertificationState.PROVISIONAL
                if geometry_authority and exact_pin
                else CertificationState.BLOCKED
            )
            if not exact_pin:
                failure_reason = "LINKED_ASSET_GEOMETRY_RELEASE_NOT_EXACTLY_PINNED"

        else:
            if not municipality or not municipality.strip():
                raise ReceiptError("municipality average requires municipality")
            if not asset_ids:
                raise ReceiptError("municipality average requires derivation_asset_ids")
            if linked_asset_id:
                raise ReceiptError(
                    "municipality average cannot carry linked_asset_id"
                )
            method = "DERIVED_AVERAGE"
            confidence = "LOW"
            geometry_authority = None
            canonicality = Canonicality.NONCANONICAL_DISPLAY_DERIVATION
            certification = CertificationState.AUDIT_ONLY

    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "producer_repo": "aguayluz-pr",
        "producer_commit_sha": producer_head,
        "event_id": event_id,
        "map_manifestation_owner": MAP_OWNER,
        "domain_authority": DOMAIN_AUTHORITY,
        "geometry_authority": geometry_authority,
        "geometry_scope": (
            "EVENT_OBSERVATION_OR_DISPLAY_DERIVATION_NOT_SHARED_REFERENCE_GEOMETRY"
        ),
        "coordinate_source": source.value,
        "coordinate_method": method,
        "coordinate_confidence": confidence,
        "geometry": geometry,
        "geometry_source_ref": geometry_source_ref,
        "linked_asset_id": linked_asset_id,
        "inherited_geometry_release_pin": dict(
            inherited_geometry_release_pin or {}
        ),
        "municipality": municipality,
        "derivation_asset_ids": list(asset_ids),
        "canonicality": canonicality.value,
        "identity_effect": "NONE",
        "displayed": displayed,
        "spatial_state": spatial_state,
        "certification_state": certification.value,
        "failure_reason": failure_reason,
    }
    core["receipt_id"] = f"maprx_{_hash_payload(core)[:32]}"
    core["logical_sha256"] = _hash_payload(core)
    validate_receipt(core)
    return core


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ReceiptError("unsupported schema_version")
    if receipt.get("map_manifestation_owner") != MAP_OWNER:
        raise ReceiptError("map manifestation owner drift")
    if receipt.get("domain_authority") != DOMAIN_AUTHORITY:
        raise ReceiptError("domain authority drift")
    if receipt.get("identity_effect") != "NONE":
        raise ReceiptError("map manifestation may not change identity")
    source = CoordinateSource(str(receipt.get("coordinate_source")))
    canonicality = Canonicality(str(receipt.get("canonicality")))
    geometry = receipt.get("geometry")
    if source is CoordinateSource.NULL:
        if geometry is not None or receipt.get("displayed") is not False:
            raise ReceiptError("NULL_EMPTY must not render")
        if canonicality is not Canonicality.NULL_EMPTY:
            raise ReceiptError("NULL_EMPTY canonicality mismatch")
    else:
        if not isinstance(geometry, Mapping) or geometry.get("type") != "Point":
            raise ReceiptError("rendered receipt must carry Point geometry")
        coords = tuple(geometry.get("coordinates") or ())
        if not _valid_point(coords if len(coords) == 2 else None):
            raise ReceiptError("invalid point geometry")
    if source is CoordinateSource.MUNICIPALITY_ASSET_AVERAGE:
        if receipt.get("geometry_authority") is not None:
            raise ReceiptError("display average has no geometry authority")
        if canonicality is not Canonicality.NONCANONICAL_DISPLAY_DERIVATION:
            raise ReceiptError("display average must remain noncanonical")
        if receipt.get("coordinate_method") != "DERIVED_AVERAGE":
            raise ReceiptError("display average method mismatch")
    if (
        source is CoordinateSource.LINKED_ASSET
        and receipt.get("coordinate_method") != "LINKED_ASSET"
    ):
        raise ReceiptError("linked asset method mismatch")
