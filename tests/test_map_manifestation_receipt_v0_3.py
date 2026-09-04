from __future__ import annotations

import copy
import pytest

from aguayluz.spatial.map_manifestation_receipt import (
    Canonicality,
    CertificationState,
    CoordinateSource,
    ReceiptError,
    build_receipt,
    validate_receipt,
)

PIN = {
    "producer_commit_sha": "a" * 40,
    "release_id": "spiderweb.geometry.test.v1",
    "logical_geometry_sha256": "b" * 64,
}


def test_direct_source_coordinates_are_preserved_lon_lat():
    row = build_receipt(
        event_id="evt-1",
        coordinate_source=CoordinateSource.DIRECT,
        coordinates=(-66.10, 18.40),
        geometry_source_ref="source-row:1",
        source_geometry_authority="USGS",
        source_coordinate_method="SOURCE_REPORTED",
        source_coordinate_confidence="HIGH",
    )
    assert row["geometry"]["coordinates"] == [-66.10, 18.40]
    assert row["canonicality"] == Canonicality.SOURCE_NATIVE_NONFEDERATION
    assert row["certification_state"] == CertificationState.PROVISIONAL


def test_direct_without_named_source_authority_stays_open():
    row = build_receipt(
        event_id="evt-2", coordinate_source="direct_event_coordinates",
        coordinates=(-66.2, 18.2), geometry_source_ref="feed:2"
    )
    assert row["geometry_authority"] is None
    assert row["certification_state"] == "OPEN"


def test_direct_requires_source_reference():
    with pytest.raises(ReceiptError, match="geometry_source_ref"):
        build_receipt(event_id="evt", coordinate_source="direct_event_coordinates", coordinates=(-66, 18))


def test_linked_asset_inherits_exact_geometry_pin():
    row = build_receipt(
        event_id="evt-3", coordinate_source="linked_asset", coordinates=(-66.3, 18.3),
        linked_asset_id="asset-9", source_geometry_authority="spiderweb-pr",
        inherited_geometry_release_pin=PIN, source_coordinate_confidence="MEDIUM"
    )
    assert row["coordinate_method"] == "LINKED_ASSET"
    assert row["geometry_authority"] == "spiderweb-pr"
    assert row["certification_state"] == "PROVISIONAL"
    assert row["identity_effect"] == "NONE"


def test_linked_asset_without_exact_pin_is_blocked():
    row = build_receipt(
        event_id="evt-4", coordinate_source="linked_asset", coordinates=(-66.3, 18.3),
        linked_asset_id="asset-9", source_geometry_authority="spiderweb-pr"
    )
    assert row["certification_state"] == "BLOCKED"
    assert row["failure_reason"] == "LINKED_ASSET_GEOMETRY_RELEASE_NOT_EXACTLY_PINNED"


def test_linked_asset_requires_asset_id():
    with pytest.raises(ReceiptError, match="linked_asset_id"):
        build_receipt(event_id="evt", coordinate_source="linked_asset", coordinates=(-66, 18))


def test_municipality_average_is_noncanonical_and_has_no_geometry_authority():
    row = build_receipt(
        event_id="evt-5", coordinate_source="municipality_asset_average",
        coordinates=(-66.4, 18.4), municipality="Bayamón",
        derivation_asset_ids=("b", "a", "a")
    )
    assert row["derivation_asset_ids"] == ["a", "b"]
    assert row["geometry_authority"] is None
    assert row["coordinate_method"] == "DERIVED_AVERAGE"
    assert row["canonicality"] == "NONCANONICAL_DISPLAY_DERIVATION"
    assert row["certification_state"] == "AUDIT_ONLY"


def test_municipality_average_requires_inputs():
    with pytest.raises(ReceiptError, match="derivation_asset_ids"):
        build_receipt(
            event_id="evt", coordinate_source="municipality_asset_average",
            coordinates=(-66, 18), municipality="Ponce"
        )


def test_null_receipt_is_explicit_and_not_displayed():
    row = build_receipt(event_id="evt-null", coordinate_source="null_empty", coordinates=None)
    assert row["geometry"] is None
    assert row["displayed"] is False
    assert row["spatial_state"] == "NULL_EMPTY"
    assert row["canonicality"] == "NULL_EMPTY"


def test_invalid_coordinates_fail_instead_of_synthesizing():
    with pytest.raises(ReceiptError, match="finite"):
        build_receipt(
            event_id="evt", coordinate_source="direct_event_coordinates",
            coordinates=(-66.0, float("nan")), geometry_source_ref="feed"
        )
    with pytest.raises(ReceiptError, match="finite"):
        build_receipt(
            event_id="evt", coordinate_source="direct_event_coordinates",
            coordinates=(-200.0, 18.0), geometry_source_ref="feed"
        )


def test_receipt_identity_is_deterministic():
    kwargs = dict(
        event_id="evt-hash", coordinate_source="direct_event_coordinates",
        coordinates=(-66.0, 18.0), geometry_source_ref="feed", source_geometry_authority="NOAA"
    )
    a = build_receipt(**kwargs)
    b = build_receipt(**kwargs)
    assert a == b
    assert len(a["logical_sha256"]) == 64


def test_coordinate_change_changes_receipt_identity():
    a = build_receipt(event_id="evt", coordinate_source="direct_event_coordinates", coordinates=(-66, 18), geometry_source_ref="feed")
    b = build_receipt(event_id="evt", coordinate_source="direct_event_coordinates", coordinates=(-66.01, 18), geometry_source_ref="feed")
    assert a["receipt_id"] != b["receipt_id"]


def test_exact_coordinate_method_never_changes_identity():
    row = build_receipt(
        event_id="evt-exact", coordinate_source="direct_event_coordinates",
        coordinates=(-66, 18), geometry_source_ref="survey:1",
        source_geometry_authority="survey-authority", source_coordinate_method="EXACT",
        source_coordinate_confidence="HIGH"
    )
    assert row["identity_effect"] == "NONE"
    assert row["geometry_scope"].endswith("NOT_SHARED_REFERENCE_GEOMETRY")


def test_validator_rejects_identity_effect():
    row = build_receipt(event_id="evt", coordinate_source="null_empty", coordinates=None)
    bad = copy.deepcopy(row)
    bad["identity_effect"] = "IDENTITY_BINDING"
    with pytest.raises(ReceiptError, match="identity"):
        validate_receipt(bad)


def test_validator_rejects_average_claiming_geometry_authority():
    row = build_receipt(
        event_id="evt", coordinate_source="municipality_asset_average",
        coordinates=(-66, 18), municipality="Ponce", derivation_asset_ids=("a",)
    )
    bad = copy.deepcopy(row)
    bad["geometry_authority"] = "aguayluz-pr"
    with pytest.raises(ReceiptError, match="no geometry authority"):
        validate_receipt(bad)


def test_unknown_coordinate_source_rejected():
    with pytest.raises(ReceiptError, match="unknown coordinate_source"):
        build_receipt(event_id="evt", coordinate_source="nearest_guess", coordinates=(-66, 18))


def test_exact_spiderweb_candidate_pin_is_immutable_and_blocked():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    pin = json.loads((root / "federation/spiderweb_archipelago_release_pin_v0_3.json").read_text())
    assert pin["producer_commit_sha"] == "3440996569d977069f782a4755f686dfcab818ba"
    assert pin["source_snapshot_sha256"] == "6e8a29fc87178264584c5e88add8ac63d8e0e9a72b9f05f63795c6edec2c92e4"
    assert pin["admission"]["runtime_activation"] is False
    assert pin["admission"]["consumer_fallback_to_latest"] is False
