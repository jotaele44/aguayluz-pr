from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "spatial_compute_shadow_v0_2.json"
BASELINE_DOC = ROOT / "docs" / "SPATIAL_BASELINE_GRID.md"
OVERLAY_DOC = ROOT / "docs" / "SPATIAL_OVERLAY_JOIN_RULES.md"


def load_contract() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_legacy_grid_is_pixel_context_only() -> None:
    grid = load_contract()["legacy_pixel_grid"]
    assert grid["dataset_id"] == "PR_SPIDERWEB_PIXEL_GRID_V1"
    assert grid["sha256"] == "17733f3f18c8a644e31c1eb25fb27b73b4bf353c6de57d5203c4311e05d64483"
    assert grid["cell_count"] == 98304
    assert grid["coordinate_domain"] == "IMAGE_PIXEL"
    assert grid["geographic_status"] == "PIXEL_CONTEXT_ONLY"
    assert grid["geographic_assignment_enabled"] is False
    assert grid["world_binding"] == {
        "crs": None,
        "bounds": None,
        "affine": None,
        "source_raster_sha256": None,
    }


def test_pixel_grid_forbids_world_space_operations() -> None:
    forbidden = set(
        load_contract()["legacy_pixel_grid"]["forbidden_operations_without_certified_world_binding"]
    )
    assert {
        "assign_crs",
        "assign_world_bounds",
        "assign_affine",
        "coordinate_to_cell_resolution",
        "municipio_join",
        "barrio_join",
        "world_space_overlay",
    } <= forbidden


def test_world_space_reference_excludes_pixel_grid() -> None:
    contract = load_contract()
    grid_path = contract["legacy_pixel_grid"]["path"]
    reference = contract["reference_overlay"]
    assert reference["left"]["path"] != grid_path
    assert reference["right"]["path"] != grid_path
    assert reference["left"]["expected_feature_count"] == 78
    assert reference["right"]["expected_feature_count"] == 901
    assert reference["expected_record_count"] == 901
    assert reference["left"]["id_field"] == "geoid"
    assert reference["right"]["id_field"] == "geoid"


def test_execution_provider_cannot_mutate_canonical_authority() -> None:
    contract = load_contract()
    authority = contract["authority"]
    providers = contract["provider_contract"]["providers"]
    assert authority["execution_provider_is_authoritative"] is False
    assert authority["local_provider_required"] is True
    assert providers["local"]["canonical_write_authority"] is False
    assert providers["wherobots"]["canonical_write_authority"] is False
    assert providers["wherobots"]["required"] is False


def test_provider_specific_fields_are_receipt_only() -> None:
    contract = load_contract()["provider_contract"]
    canonical = contract["canonical_output_fields"]
    prefixes = tuple(contract["forbidden_canonical_field_prefixes"])
    assert all(not field.startswith(prefixes) for field in canonical)
    assert "provider_name" in contract["runtime_receipt_only_fields"]
    assert "execution_id" in contract["runtime_receipt_only_fields"]


def test_docs_explicitly_block_legacy_geographic_resolution() -> None:
    baseline = BASELINE_DOC.read_text(encoding="utf-8")
    overlay = OVERLAY_DOC.read_text(encoding="utf-8")
    assert "PIXEL_CONTEXT_ONLY" in baseline
    assert "no certified world-space binding" in baseline
    assert "geographic_assignment_enabled` is false" in baseline
    assert "coordinate_to_cell_resolution_allowed: false" in overlay
    assert "MUST NOT be joined to `Cell_ID` through an inferred transform" in overlay
