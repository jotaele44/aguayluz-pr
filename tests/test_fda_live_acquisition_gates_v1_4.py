from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "research/regulatory/fda_live_source_registry_v1_4.json"
DESIGN = ROOT / "docs/fda_live_acquisition_gates_v1_4.md"


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_registry_is_design_only_and_requires_separate_authorization() -> None:
    registry = load_registry()
    assert registry["status"] == "design_only_disabled"
    activation = registry["activation"]
    assert activation == {
        "network_implementation_allowed": False,
        "scheduler_registration_allowed": False,
        "production_persistence_allowed": False,
        "credentials_allowed": False,
        "requires_separate_explicit_authorization": True,
    }


def test_all_sources_have_authority_and_inference_boundaries() -> None:
    registry = load_registry()
    assert len(registry["sources"]) == 6
    for source in registry["sources"]:
        assert source["source_id"].startswith("FDA_")
        assert source["authority"].startswith("official_fda")
        assert source["access_modes"]
        assert source["canonical_limit"]
        assert source["prohibitions"]


def test_inspection_source_is_explicitly_non_comprehensive() -> None:
    registry = load_registry()
    inspection = next(
        source
        for source in registry["sources"]
        if source["source_id"] == "FDA_INSPECTION_CLASSIFICATION_DASHBOARD"
    )
    assert "non_comprehensive" in inspection["canonical_limit"]
    assert "never_claim_complete_inspection_universe" in inspection["prohibitions"]
    assert "do_not_treat_absence_as_no_inspection" in inspection["prohibitions"]


def test_warning_letters_are_not_final_adjudications() -> None:
    registry = load_registry()
    warning = next(
        source for source in registry["sources"] if source["source_id"] == "FDA_WARNING_LETTERS"
    )
    assert "do_not_treat_warning_letter_as_final_adjudication" in warning["prohibitions"]
    assert "preserve_response_and_closeout_links" in warning["prohibitions"]


def test_global_controls_require_provenance_and_terms_review() -> None:
    controls = load_registry()["global_controls"]
    assert controls["deny_redirect_to_unlisted_host"] is True
    assert controls["raw_bytes_required"] is True
    assert controls["sha256_required"] is True
    assert controls["retrieved_at_required"] is True
    assert controls["source_url_required"] is True
    assert controls["normalizer_version_required"] is True
    assert controls["terms_snapshot_required_before_activation"] is True


def test_design_contains_no_live_implementation_imports_or_endpoints() -> None:
    source = "\n".join(
        [
            REGISTRY.read_text(encoding="utf-8"),
            DESIGN.read_text(encoding="utf-8"),
            Path(__file__).read_text(encoding="utf-8"),
        ]
    ).lower()
    forbidden = (
        "import httpx",
        "import requests",
        "urllib.request",
        "import socket",
        "import sqlite3",
        "sqlalchemy",
        "apscheduler",
        "api_key =",
        "authorization: bearer",
    )
    assert not any(token in source for token in forbidden)
