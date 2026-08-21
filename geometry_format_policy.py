from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GeometryState = Literal["PASS", "FAIL", "BLOCKED", "NONCANONICAL"]


@dataclass(frozen=True)
class TWKBAdmission:
    state: GeometryState
    reason: str


def assess_twkb_admission(
    *,
    source_frozen: bool,
    crs: str | None,
    coordinate_units: str | None,
    dimension: str | None,
    xy_precision: int | None,
    z_precision: int | None = None,
    has_z: bool = False,
    roundtrip_ok: bool,
    type_conserved: bool,
    null_empty_conserved: bool,
    validity_conserved: bool,
    vertex_count_conserved: bool,
    application_tolerance: float | None,
    observed_max_error: float | None,
    canonical_copy_retained: bool,
) -> TWKBAdmission:
    """Fail-closed admission gate for TWKB as a derived geometry encoding.

    This gate never promotes TWKB to canonical geometry. It only determines
    whether a compact derivative may be emitted alongside an independently
    retained canonical/source representation.
    """
    required = {
        "source not frozen": source_frozen,
        "CRS missing": bool(crs),
        "coordinate units missing": bool(coordinate_units),
        "dimension missing": bool(dimension),
        "XY precision implicit/missing": xy_precision is not None,
        "canonical copy not retained": canonical_copy_retained,
    }
    for reason, ok in required.items():
        if not ok:
            return TWKBAdmission("BLOCKED", reason)
    if has_z and z_precision is None:
        return TWKBAdmission("BLOCKED", "Z precision implicit/missing")
    if application_tolerance is None:
        return TWKBAdmission("BLOCKED", "application tolerance missing")
    if not all(
        [
            roundtrip_ok,
            type_conserved,
            null_empty_conserved,
            validity_conserved,
            vertex_count_conserved,
        ]
    ):
        return TWKBAdmission("FAIL", "round-trip conservation invariant failed")
    if observed_max_error is None:
        return TWKBAdmission("BLOCKED", "observed round-trip error missing")
    if observed_max_error > application_tolerance:
        return TWKBAdmission("FAIL", "quantization error exceeds application tolerance")
    return TWKBAdmission("NONCANONICAL", "derived compact encoding admitted; canonical geometry retained")
