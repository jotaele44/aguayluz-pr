"""Pure geometry/time/search primitives behind the /gis/* API (spiderweb/gis_query.py)."""

from __future__ import annotations

import csv
import io

import pytest

from aguayluz import gis_query as gq
from aguayluz.gis_geodesy import geodesic_distance_m

SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[-66.2, 18.2], [-66.0, 18.2], [-66.0, 18.4], [-66.2, 18.4], [-66.2, 18.2]]
    ],
}
SQUARE_WITH_HOLE = {
    "type": "Polygon",
    "coordinates": [
        [[-66.2, 18.2], [-66.0, 18.2], [-66.0, 18.4], [-66.2, 18.4], [-66.2, 18.2]],
        [
            [-66.15, 18.25],
            [-66.05, 18.25],
            [-66.05, 18.35],
            [-66.15, 18.35],
            [-66.15, 18.25],
        ],
    ],
}


def point(lon, lat, **props):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def test_polygon_aoi_contains_interior_point_and_boundary_is_inclusive():
    area = gq.parse_geometry({"type": "polygon", "geojson": SQUARE})
    assert area.mode == "polygon"
    assert gq.intersects(gq.feature_parts(point(-66.1, 18.3)), area)
    assert gq.intersects(gq.feature_parts(point(-66.0, 18.3)), area)  # on the east edge
    assert not gq.intersects(gq.feature_parts(point(-65.99, 18.3)), area)


def test_polygon_hole_excludes_points_inside_it_but_not_on_its_edge():
    area = gq.parse_geometry({"type": "geojson", "geojson": SQUARE_WITH_HOLE})
    assert not gq.intersects(gq.feature_parts(point(-66.1, 18.3)), area)
    assert gq.intersects(gq.feature_parts(point(-66.15, 18.3)), area)
    assert gq.intersects(gq.feature_parts(point(-66.18, 18.3)), area)


def test_unclosed_ring_is_closed_and_degenerate_ring_rejected():
    open_ring = {
        "type": "Polygon",
        "coordinates": [[[-66.2, 18.2], [-66.0, 18.2], [-66.0, 18.4]]],
    }
    area = gq.parse_geometry({"type": "polygon", "geojson": open_ring})
    assert area.polygons[0][0][0] == area.polygons[0][0][-1]
    with pytest.raises(gq.GisQueryError):
        gq.parse_geometry(
            {
                "type": "polygon",
                "geojson": {"type": "Polygon", "coordinates": [[[-66, 18], [-65, 18]]]},
            }
        )


def test_radius_matches_geodesic_distance():
    centre = (-66.1, 18.3)
    near, far = point(-66.1, 18.309), point(-66.1, 18.311)
    d_near = geodesic_distance_m(*centre, -66.1, 18.309)
    d_far = geodesic_distance_m(*centre, -66.1, 18.311)
    radius = (d_near + d_far) / 2
    area = gq.parse_geometry(
        {"type": "radius", "lon": centre[0], "lat": centre[1], "radius_m": radius}
    )
    assert gq.intersects(gq.feature_parts(near), area)
    assert not gq.intersects(gq.feature_parts(far), area)


def test_bbox_rejects_inverted_or_antimeridian_boxes():
    with pytest.raises(gq.GisQueryError):
        gq.parse_geometry(
            {"type": "bbox", "west": -65, "south": 18, "east": -66, "north": 18.5}
        )
    area = gq.parse_geometry(
        {"type": "bbox", "west": -66.2, "south": 18.2, "east": -66.0, "north": 18.4}
    )
    assert gq.intersects(gq.feature_parts(point(-66.1, 18.3)), area)


def test_line_crossing_polygon_without_vertex_inside_still_intersects():
    line = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-66.3, 18.3], [-65.9, 18.3]],
        },
        "properties": {},
    }
    area = gq.parse_geometry({"type": "polygon", "geojson": SQUARE})
    assert gq.intersects(gq.feature_parts(line), area)


def test_aoi_fully_inside_a_polygon_feature_intersects_it():
    big = {"type": "Feature", "geometry": SQUARE, "properties": {}}
    small = gq.parse_geometry(
        {"type": "bbox", "west": -66.11, "south": 18.29, "east": -66.09, "north": 18.31}
    )
    assert gq.intersects(gq.feature_parts(big), small)


def test_query_layer_counts_features_without_geometry_as_excluded():
    features = [
        point(-66.1, 18.3, id="a"),
        {"type": "Feature", "geometry": None, "properties": {"id": "b"}},
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [999, 18]},
            "properties": {"id": "c"},
        },
    ]
    area = gq.parse_geometry({"type": "polygon", "geojson": SQUARE})
    result = gq.query_layer("demo", features, area)
    assert result["matched_count"] == 1
    assert result["excluded_count"] == 2
    assert result["truncated"] is False


def test_query_layer_truncates_but_reports_full_match_count():
    features = [point(-66.1, 18.3, id=str(i)) for i in range(5)]
    area = gq.parse_geometry({"type": "polygon", "geojson": SQUARE})
    result = gq.query_layer("demo", features, area, limit=2)
    assert (result["matched_count"], result["returned_count"], result["truncated"]) == (
        5,
        2,
        True,
    )


def test_time_range_filters_and_excludes_unparseable_times():
    features = [
        point(-66.1, 18.3, when="1975-06-01"),
        point(-66.1, 18.3, when="1985"),
        point(-66.1, 18.3, when="unknown"),
        point(-66.1, 18.3, when="1979-12-31T22:00:00"),
    ]
    area = gq.parse_geometry({"type": "polygon", "geojson": SQUARE})
    result = gq.query_layer(
        "demo",
        features,
        area,
        temporal_field="when",
        time_range=gq.parse_time_range({"start": "1970", "end": "1979"}),
    )
    assert result["matched_count"] == 2
    assert result["excluded_count"] == 1


def test_parse_time_range_rejects_reversed_or_garbage_ranges():
    with pytest.raises(gq.GisQueryError):
        gq.parse_time_range({"start": "1990", "end": "1980"})
    with pytest.raises(gq.GisQueryError):
        gq.parse_time_range({"start": "not-a-date"})
    assert gq.normalize_time("2024-02", upper=True) == "2024-02-29T23:59:59"


def test_identify_returns_nearest_first_within_tolerance():
    features = [
        point(-66.1, 18.3001, id="far"),
        point(-66.1, 18.30001, id="near"),
        point(-66.2, 18.3, id="out"),
    ]
    hits = gq.identify(features, -66.1, 18.3, tolerance_m=30)
    assert [gq.feature_identifier(f) for _d, f in hits] == ["near", "far"]
    polygon_feature = {
        "type": "Feature",
        "geometry": SQUARE,
        "properties": {"id": "sq"},
    }
    assert gq.identify([polygon_feature], -66.1, 18.3)[0][0] == 0.0


def test_search_is_accent_insensitive_and_ranked():
    features = [
        point(-66, 18, name="Río Grande de Loíza"),
        point(-66, 18, name="Mayagüez"),
        point(-66, 18, name="Bahía de Mayagüez"),
    ]
    hits = gq.search_features(features, "mayaguez", ["name"])
    assert [h["value"] for h in hits] == ["Mayagüez", "Bahía de Mayagüez"]
    assert [h["rank"] for h in hits] == [0, 2]
    assert gq.search_features(features, "loiza", ["name"])[0]["rank"] == 2
    assert gq.search_features(features, "zzz", ["name"]) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("18.4723, -66.7156", (-66.7156, 18.4723)),
        ("-66.7156 18.4723", (-66.7156, 18.4723)),
        (
            "18°28'20\"N 66°42'56\"W",
            (-(66 + 42 / 60 + 56 / 3600), 18 + 28 / 60 + 20 / 3600),
        ),
    ],
)
def test_parse_coordinate_text(text, expected):
    lon, lat = gq.parse_coordinate_text(text)
    assert lon == pytest.approx(expected[0])
    assert lat == pytest.approx(expected[1])


def test_parse_coordinate_text_is_linear_on_adversarial_whitespace():
    # CodeQL py/polynomial-redos: long whitespace runs must not backtrack.
    assert gq.parse_coordinate_text("1" + "\t" * 50_000 + "x") is None
    assert gq.parse_coordinate_text("18" + " " * 40 + "-66") == (-66.0, 18.0)
    assert gq.parse_coordinate_text("18°" + " " * 30 + "28'N 66°42'W") is not None
    assert gq.parse_coordinate_text("18.4723") is None  # never split one number in two


def test_parse_coordinate_text_rejects_non_coordinates():
    assert gq.parse_coordinate_text("Arecibo") is None
    assert gq.parse_coordinate_text("200, 300") is None


def test_features_to_csv_has_anchor_and_union_of_properties():
    body = gq.features_to_csv(
        [point(-66.1, 18.3, id="a", name="x"), point(-66.2, 18.2, id="b", kind="y")]
    )
    rows = list(csv.DictReader(io.StringIO(body)))
    assert rows[0]["feature_id"] == "a" and rows[0]["anchor_lon"] == "-66.1"
    assert set(rows[0]) >= {"name", "kind", "geometry_type"}


def test_summarize_counts_missing_values_explicitly():
    summary = gq.summarize([point(0, 0, k="a"), point(0, 0, k="a"), point(0, 0)], ["k"])
    assert summary == {"k": {"a": 2, "(missing)": 1}}
