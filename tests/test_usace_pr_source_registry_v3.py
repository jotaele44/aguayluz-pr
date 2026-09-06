from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_operator_module():
    path = _repo_root() / "operators" / "harvest_usace_pr_v3.py"
    spec = importlib.util.spec_from_file_location("harvest_usace_pr_v3", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registry() -> dict:
    return json.loads((_repo_root() / "data/usace_pr/source_registry_v3.json").read_text())


def test_registry_source_ids_are_unique_and_count_closes() -> None:
    registry = _registry()
    rows = registry["sources"]
    ids = [row["source_id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert len(rows) == registry["certification_invariants"]["declared_source_count"] == 16


def test_rrs_is_current_primary_and_jacksonville_is_backfill() -> None:
    rows = {row["source_id"]: row for row in _registry()["sources"]}
    assert rows["rrs_public_notices_pr"]["role"] == "CURRENT_REGULATORY_SOURCE"
    assert rows["rrs_public_notices_pr"]["temporal_role"] == "CURRENT_PRIMARY_FROM_2025"
    assert rows["saj_regulatory_public_notices_pr"]["role"] == "HISTORICAL_BACKFILL_SOURCE"
    assert rows["sad_puerto_rico_regulatory_portal"]["role"] == "SECONDARY_REFERENCE_SOURCE"
    assert rows["orm_public_pr"]["role"] == "CURRENT_REGULATORY_SOURCE"


def test_current_regulatory_blockers_prevent_certification() -> None:
    module = _load_operator_module()
    rows = {row["source_id"]: row for row in _registry()["sources"]}
    assert module.classify_execution(rows["rrs_public_notices_pr"]) == "BLOCKED"
    assert module.classify_execution(rows["orm_public_pr"]) == "BLOCKED"
    assert module.classify_execution(rows["sad_puerto_rico_regulatory_portal"]) == "REFERENCE_OR_CROSSCHECK"


def test_mixed_index_sources_have_deterministic_bounds() -> None:
    rows = _registry()["sources"]
    mixed = [row for row in rows if row.get("adapter") == "generic_mixed_index"]
    assert mixed
    assert all(row.get("include_href_regex") for row in mixed)


def test_waterbody_universe_reuses_existing_aguayluz_hydrography() -> None:
    waterbody = _registry()["waterbody_universe"]
    assert "NHDPlus V2.1" in waterbody["primary"]
    assert "Reuse passed AguaYLuz" in waterbody["reuse_rule"]
    assert "marine" in waterbody["marine_rule"].casefold() or "bays" in waterbody["marine_rule"].casefold()


def test_reference_sources_do_not_satisfy_primary_source_execution() -> None:
    module = _load_operator_module()
    rows = _registry()["sources"]
    refs = [row for row in rows if row["role"] == "SECONDARY_REFERENCE_SOURCE"]
    assert refs
    assert all(module.classify_execution(row) == "REFERENCE_OR_CROSSCHECK" for row in refs)
