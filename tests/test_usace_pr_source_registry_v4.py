from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from aguayluz.usace_family import FamilyLink, family_arithmetic


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _registry() -> dict:
    return json.loads((_root() / "data/usace_pr/source_registry_v4.json").read_text())


def _load_operator():
    path = _root() / "operators/harvest_usace_pr_v4.py"
    spec = importlib.util.spec_from_file_location("harvest_usace_pr_v4", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v4_bounded_source_count_and_ids_close() -> None:
    registry = _registry()
    rows = registry["sources"]
    ids = [row["source_id"] for row in rows]
    assert len(rows) == registry["certification_invariants"]["declared_source_count"] == 16
    assert len(ids) == len(set(ids))


def test_current_regulatory_sources_are_required_and_blocking() -> None:
    module = _load_operator()
    rows = {row["source_id"]: row for row in _registry()["sources"]}
    rrs = rows["rrs_public_notices_pr"]
    orm = rows["orm_public_pr"]
    assert rrs["role"] == orm["role"] == "CURRENT_REGULATORY_SOURCE"
    assert rrs["district_code"] == "SAA"
    assert module.execution_class(rrs) == "BLOCKED"
    assert module.execution_class(orm) == "BLOCKED"


def test_erdc_dspace_adapter_is_executable_but_not_predeclared_pass() -> None:
    module = _load_operator()
    rows = {row["source_id"]: row for row in _registry()["sources"]}
    erdc = rows["erdc_knowledge_core"]
    assert erdc["adapter"] == "dspace7_api"
    assert erdc["adapter_state"] == "IMPLEMENTED_NEEDS_LIVE_EXECUTION"
    assert module.execution_class(erdc) == "EXECUTE"


def test_pal_resolver_does_not_satisfy_exhaustive_source_gate() -> None:
    module = _load_operator()
    rows = {row["source_id"]: row for row in _registry()["sources"]}
    pal = rows["iwr_project_assistance_library"]
    assert pal["search_request_schema_bound"] is False
    assert pal["adapter_state"].startswith("BLOCKED_")
    assert module.execution_class(pal) == "BLOCKED"


def test_reference_sources_do_not_define_project_identity() -> None:
    module = _load_operator()
    refs = [
        row
        for row in _registry()["sources"]
        if row["role"] == "SECONDARY_REFERENCE_SOURCE"
    ]
    assert refs
    assert all(module.execution_class(row) == "REFERENCE_OR_CROSSCHECK" for row in refs)


def test_waterbody_contract_forbids_name_only_identity() -> None:
    universe = _registry()["waterbody_universe"]
    assert "NHDPlus V2.1" in universe["primary"]
    assert "GNIS" in " ".join(universe["crosschecks"])
    assert "normalized names" in universe["identity_rule"].lower()


def test_family_arithmetic_defaults_unclassified_links_to_unresolved() -> None:
    rows = [
        FamilyLink("p", "a.pdf", "https://x.test/a.pdf", "A", "DIRECT_MANIFESTATION", 1, "DISCOVERED_NOT_IDENTITY"),
        FamilyLink("p", "b.pdf", "https://x.test/b.pdf", "B", "DIRECT_MANIFESTATION", 1, "DISCOVERED_NOT_IDENTITY"),
    ]
    receipt = family_arithmetic(rows, {"https://x.test/a.pdf": "RETRIEVED"})
    assert receipt["family_total"] == 2
    assert receipt["retrieved"] == 1
    assert receipt["unresolved"] == 1
