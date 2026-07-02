import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aguayluz.models import validate_against_schema  # noqa: E402
from import_local_hydro_assets import (  # noqa: E402
    COASTAL_OUTLET_LAYERS,
    CSV_SPECS,
    MAX_IMPORT_ROWS_BY_LAYER,
    SHAPEFILE_SPECS,
    XLSX_SHEET_SPECS,
    _layer_spec,
    csv_spec_for,
    iter_csv,
    iter_geojson,
    merge,
)

# --- kept sources still import and validate ---------------------------------


def test_iter_csv_intake_outfall_is_schema_valid(tmp_path):
    csv_path = tmp_path / "PRASA_Intakes_Outfalls_v1.csv"
    csv_path.write_text(
        "name,operator,lat,lon\n"
        "Lago La Plata Intake,PRASA,18.388,-66.232\n",
        encoding="utf-8",
    )
    rows = list(iter_csv(csv_path, CSV_SPECS["PRASA_Intakes_Outfalls_v1.csv"]))
    assert len(rows) == 1
    row = rows[0]
    assert row["asset_type"] == "water"
    assert row["asset_subtype"] == "intake_outfall"
    assert row["lat"] == pytest.approx(18.388)
    validate_against_schema("utility_asset", row)


def test_iter_geojson_nid_dam_is_schema_valid(tmp_path):
    geojson_path = tmp_path / "NID_AUTH_MASTER.geojson"
    geojson_path.write_text(json.dumps({
        "features": [{
            "type": "Feature",
            "properties": {"NIDID": "PR00042", "name": "Lago Guajataca Dam", "owner": "PRASA"},
            "geometry": {"type": "Point", "coordinates": [-66.9, 18.4]},
        }]
    }), encoding="utf-8")
    rows = list(iter_geojson(geojson_path, "NID", "dam", "water"))
    assert len(rows) == 1
    row = rows[0]
    assert row["asset_type"] == "water" and row["asset_subtype"] == "dam"
    assert row["asset_id"].startswith("NID_")
    validate_against_schema("utility_asset", row)


def test_merge_is_idempotent_and_keyed_by_asset_id(tmp_path):
    csv_path = tmp_path / "PRASA_Intakes_Outfalls_v1.csv"
    csv_path.write_text(
        "name,operator,lat,lon\nIntake A,PRASA,18.1,-66.1\n", encoding="utf-8"
    )
    rows = list(iter_csv(csv_path, CSV_SPECS["PRASA_Intakes_Outfalls_v1.csv"]))
    once = merge([], rows)
    twice = merge(once, rows)
    assert len(once) == len(twice) == 1


# --- scope trim: natural-hydrography reference layers are dropped -----------


@pytest.mark.parametrize("filename", [
    "FEATURE_MASTER.csv",
    "KARST_EXTENSION.csv",
    "UGCN_MASTER_ILAP_TABLE_v1.csv",
    "widl_nodes.csv",
    "icg_priority_zones.csv",
    "Hydro_ILAP_Node_Vulnerability_Table.csv",
])
def test_dropped_csv_sources_are_unrecognized(filename):
    assert csv_spec_for(Path(filename)) is None
    assert filename not in CSV_SPECS


@pytest.mark.parametrize("sheet", [
    "HYDRO_FEATURES_FULL",
    "EPA_NPDES_CATCHMENTS_PR",
    "SURFACE_LINEARWATER",
    "HL_WATERSHED_CONTEXT",
    "EPA_ATTAINS_RECEIVING_WATERS_PR",
])
def test_dropped_xlsx_sheets_are_unrecognized(sheet):
    assert sheet not in XLSX_SHEET_SPECS


@pytest.mark.parametrize("layer", [
    "nhdarea_pr", "nhdline_pr", "nhdpoint_pr", "nhdflowline_pr",
    "nhdwaterbody_pr", "catchment_fabric_pr",
    "Wetlands", "PRVI_Wetlands", "PuertoRico",
    "Gaz_Features", "DomesticNames", "HistoricalFeatures",
])
def test_dropped_gpkg_layers_have_no_spec(layer):
    assert _layer_spec(Path("irrelevant.gpkg"), layer) is None


def test_dropped_shapefiles_are_unrecognized():
    for name in ("BurnAddLine.shp", "BurnAddWaterbody.shp", "BurnWaterbody.shp",
                 "Sink.shp", "Wall.shp", "LandSea.shp"):
        assert name not in SHAPEFILE_SPECS
    # A named reservoir's shoreline is real infrastructure and stays.
    assert "Carite_shr83.shp" in SHAPEFILE_SPECS


def test_aquifer_boundary_layer_dropped():
    assert "aquifer_context_pr" not in COASTAL_OUTLET_LAYERS


def test_no_row_caps_remain_for_dropped_layers():
    # MAX_IMPORT_ROWS_BY_LAYER previously capped NHDPlus/wetland layers that no
    # longer exist in the importer at all.
    assert MAX_IMPORT_ROWS_BY_LAYER == {}


def test_kept_infrastructure_layers_still_have_specs():
    assert _layer_spec(Path("irrelevant.gpkg"), "Dams") == (
        "water", "dam", "point", "National Inventory of Dams"
    )
    assert _layer_spec(Path("irrelevant.gpkg"), "qa_outlet_points_v2_1_all") is not None
    assert _layer_spec(Path("irrelevant.gpkg"), "water_treatment_plant") == (
        "water", "treatment_plant", "point", "PRASA/AAA"
    )
