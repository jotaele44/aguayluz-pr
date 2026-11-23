"""gis-layer-catalog/1.0 built from config/gis_layer_catalog.yaml."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from aguayluz.gis_catalog import GisCatalogError, build_gis_catalog

jsonschema = pytest.importorskip("jsonschema")

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def config() -> dict:
    return yaml.safe_load((ROOT / "config" / "gis_layer_catalog.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    ["gis_layer_catalog_v1.schema.json", "gis_query_v1.schema.json", "gis_scenario_result_v1.schema.json"],
)
def test_mirrored_gis_schemas_are_valid_draft_2020_12(name):
    jsonschema.Draft202012Validator.check_schema(_schema(name))


def test_catalog_validates_against_the_mirrored_contract(config):
    document = build_gis_catalog(config, data_available=lambda _layer: True)
    jsonschema.validate(document, _schema("gis_layer_catalog_v1.schema.json"))
    assert document["producer_repo"] == "aguayluz-pr"


def test_karst_layer_is_blocked_without_geometry_or_export(config):
    by_id = {layer["layer_id"]: layer for layer in build_gis_catalog(config)["layers"]}
    karst = by_id["cave_karst"]
    assert karst["status"] == "blocked"
    assert karst["source"]["kind"] == "none"
    assert karst["exportable"] is False
    assert "public_exact" in karst["blocked_reason"]


def test_capacity_symbology_is_declared_data_blocked(config):
    power = {layer["layer_id"]: layer for layer in build_gis_catalog(config)["layers"]}["power_assets"]
    assert power["classification"] == {"field": "asset_subtype", "method": "categorical"}
    assert "capacity" in power["classification_blocked_reason"]


def test_zoom_thresholds_stay_unset_until_measured(config):
    assert all(
        layer["min_zoom"] is None and layer["max_zoom"] is None
        for layer in build_gis_catalog(config)["layers"]
    )


def test_duplicate_layer_ids_are_rejected():
    with pytest.raises(GisCatalogError):
        build_gis_catalog({"layers": [{"layer_id": "a"}, {"layer_id": "a"}]})
