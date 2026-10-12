"""Municipio point binding for the hydromet plane (real Census polygons + real gauges).

Coordinates and NWPS county names are from tests/fixtures/nwps_gauge_details/.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from aguayluz.hazard_plane import EvidenceClass, SpatialState  # noqa: E402
from aguayluz.hydromet.spatial import MunicipioIndex, municipio_key  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "nwps_gauge_details"


@pytest.fixture(scope="module")
def index():
    return MunicipioIndex.from_geojson()


def _gauge(lid):
    return json.loads((FIXTURES / f"{lid}.json").read_text())


def test_point_inside_with_matching_source_name(index):
    g = _gauge("QUEP4")
    binding = index.bind_point(g["longitude"], g["latitude"], g["county"])
    assert binding.geoid and binding.municipio == "Quebradillas"
    assert binding.evidence_class == EvidenceClass.POINT_IN_POLYGON_WITH_ALIAS
    assert binding.spatial_state == SpatialState.FULLY_WITHIN


def test_disagreement_stays_unresolved_with_candidate(index):
    # Río Grande de Loíza at Caguas sits on the Caguas/Gurabo line: the polygon says
    # one municipio, NWPS says the other. Neither is adopted.
    g = _gauge("CAGP4")
    binding = index.bind_point(g["longitude"], g["latitude"], g["county"])
    assert binding.geoid is None
    assert binding.evidence_class == EvidenceClass.UNRESOLVED
    assert binding.candidate_geoid and binding.candidate_municipio
    assert municipio_key(binding.candidate_municipio) != municipio_key(g["county"])


def test_offshore_tide_gauge_snaps_only_with_source_alias(index):
    g = _gauge("ESPP4")
    binding = index.bind_point(g["longitude"], g["latitude"], g["county"])
    assert binding.municipio == "Vieques"
    assert binding.evidence_class == EvidenceClass.ALIAS_WITH_SPATIOTEMPORAL_SUPPORT
    assert binding.spatial_state == SpatialState.OUTSIDE
    assert 0 < binding.distance_m <= 1500
    no_alias = index.bind_point(g["longitude"], g["latitude"], None)
    assert no_alias.geoid is None and no_alias.evidence_class == EvidenceClass.UNRESOLVED


def test_missing_alias_is_point_in_polygon_only(index):
    g = _gauge("NGIP4")
    assert g["county"] == ""
    binding = index.bind_point(g["longitude"], g["latitude"], g["county"])
    assert binding.evidence_class == EvidenceClass.POINT_IN_POLYGON
    assert binding.municipio == "Naguabo"


def test_no_coordinates_never_becomes_island_wide(index):
    binding = index.bind_point(None, None, "San Juan")
    assert binding.geoid is None
    assert binding.spatial_state == SpatialState.NULL_EMPTY


def test_far_offshore_point_is_unresolved(index):
    binding = index.bind_point(-66.4, 17.2, "Ponce")
    assert binding.geoid is None
    assert binding.evidence_class == EvidenceClass.UNRESOLVED


def test_name_key_ignores_accents_and_case():
    assert municipio_key("Mayagüez") == municipio_key("MAYAGUEZ") == "mayaguez"
    assert index is not None


def test_raster_cells_fall_back_to_touching_cells_and_never_widen_an_empty_zone():
    # CONSTRUCTED: a 4×4 grid of 1° cells (x 0-4, y 0-4) and three polygons — one holding
    # four cell centres, one too small to hold a centre that touches a single cell, and
    # one off the grid.
    pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    from shapely.geometry import box, mapping

    from aguayluz.hydromet.spatial import raster_cells_by_municipio

    def feature(name, geoid, geom):
        return {"type": "Feature", "properties": {"name": name, "geoid": geoid}, "geometry": mapping(geom)}

    synthetic = MunicipioIndex([
        feature("Grande", "1", box(0.1, 0.1, 1.9, 1.9)),
        feature("Pequeño", "2", box(2.1, 2.1, 2.3, 2.3)),
        feature("Lejos", "3", box(10, 10, 11, 11)),
    ])
    by_name = {s.municipio: s for s in raster_cells_by_municipio(synthetic, "EPSG:4326", from_origin(0, 4, 1, 1), (4, 4))}

    grande, pequeno, lejos = by_name["Grande"], by_name["Pequeño"], by_name["Lejos"]
    assert (grande.method, grande.spatial_state, grande.cell_count) == (
        "raster_cell_centres_in_polygon", SpatialState.FULLY_WITHIN, 4)
    assert grande.mask[2:4, 0:2].all()  # rows 2-3 = y 0-2, columns 0-1 = x 0-2
    assert (pequeno.method, pequeno.spatial_state, pequeno.cell_count) == (
        "raster_cells_touching_polygon", SpatialState.PARTIAL, 1)
    assert pequeno.mask[1, 2]  # the cell spanning x 2-3, y 2-3
    assert (lejos.method, lejos.spatial_state, lejos.cell_count) == (
        "no_raster_cell", SpatialState.NULL_EMPTY, 0)
