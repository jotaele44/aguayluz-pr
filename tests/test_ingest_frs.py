"""Tests for the EPA Facility Registry Service (FRS) adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aguayluz.ingest.frs import infer_asset_type, parse_frs_response

FIXTURES = Path(__file__).parent / "fixtures" / "frs"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------- infer_asset_type ----------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("LUMA CATANO SUBSTATION", ("power", "substation", True)),
        ("AES Puerto Rico Power Plant", ("power", "generation_plant", True)),
        ("PRASA BAYAMON NORTE WWTP", ("wastewater", "treatment_plant", True)),
        ("Carolina Wastewater Treatment", ("wastewater", "treatment_plant", True)),
        ("Bayamon Water Treatment Plant", ("water", "treatment_plant", True)),
        ("EBAR North Pump Station", ("water", "pump_station", True)),
        ("Lago La Plata Reservoir", ("water", "reservoir", True)),
        ("LAGO CARRAIZO", ("water", "reservoir", True)),
        ("Cellular Tower #12", ("telecom", "tower", True)),
        ("Bayamon Regional Hospital", ("unknown", "facility", False)),
        ("APOLONIA APARTMENTS", ("unknown", "facility", False)),
        ("CONCRETE INDUSTRIES", ("unknown", "facility", False)),
    ],
)
def test_classifier(name, expected):
    assert infer_asset_type(name) == expected


def test_wastewater_beats_water_keyword():
    # 'WASTEWATER' contains 'WATER' — the classifier must check wastewater first.
    asset_type, _, _ = infer_asset_type("BAYAMON WASTEWATER FACILITY")
    assert asset_type == "wastewater"


# ---------- parse_frs_response ----------


def test_parse_frs_full_fixture():
    seeds = parse_frs_response(_load("pr_bayamon_npdes.json"))
    assert len(seeds) == 6
    by_name = {s.name: s for s in seeds}
    assert "BAYAMON WATER TREATMENT PLANT" in by_name
    assert by_name["BAYAMON WATER TREATMENT PLANT"].asset_type == "water"
    assert by_name["BAYAMON WATER TREATMENT PLANT"].asset_subtype == "treatment_plant"
    assert by_name["PRASA BAYAMON NORTE WWTP"].asset_type == "wastewater"
    assert by_name["LUMA CATANO SUBSTATION"].asset_type == "power"


def test_parse_frs_null_coords_preserved():
    seeds = parse_frs_response(_load("pr_bayamon_npdes.json"))
    apt = next(s for s in seeds if s.name == "APOLONIA APARTMENTS")
    assert apt.lat is None
    assert apt.lon is None
    assert apt.is_utility is False  # apartments aren't utilities


def test_parse_frs_municipality_titlecased():
    seeds = parse_frs_response(_load("pr_bayamon_npdes.json"))
    cats = [s for s in seeds if "CATANO" in s.name.upper()]
    assert cats
    assert cats[0].municipality == "Catano"


def test_parse_frs_seed_id_prefix():
    seeds = parse_frs_response(_load("pr_bayamon_npdes.json"))
    for s in seeds:
        assert s.seed_id.startswith("AYL_AST_FRS_")


def test_parse_frs_empty_response():
    assert parse_frs_response({"Results": {"FRSFacility": []}}) == []
    assert parse_frs_response({}) == []


def test_parse_frs_provenance_recorded():
    seeds = parse_frs_response(_load("pr_bayamon_npdes.json"))
    assert all("EPA Facility Registry Service" in s.source_provenance for s in seeds)
