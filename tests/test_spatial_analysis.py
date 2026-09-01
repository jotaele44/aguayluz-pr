from aguayluz.spatial_analysis import (
    DirectedEdge,
    RasterSpec,
    impacted_assets,
    raster_layer_contract,
    trace_downstream,
    trace_upstream,
)

EDGES = [
    DirectedEdge("A", "B"),
    DirectedEdge("B", "C"),
    DirectedEdge("B", "D"),
    DirectedEdge("D", "E"),
]


def test_hydro_traces_are_directional_and_cycle_safe():
    assert trace_downstream("A", EDGES) == ["B", "C", "D", "E"]
    assert trace_upstream("E", EDGES) == ["D", "B", "A"]


def test_impacted_assets():
    assets = {"plant": "A", "pump": "C", "tank": "E", "unrelated": "Z"}
    assert impacted_assets("B", EDGES, assets) == ["pump", "tank"]


def test_raster_contract_validation():
    spec = RasterSpec(
        "dem",
        "s3://bucket/dem.tif",
        "EPSG:32161",
        (-67.3, 17.8, -65.2, 18.6),
        10,
        10,
        source_authority="USGS",
    )
    payload = raster_layer_contract(spec)
    assert payload["geometry_types"] == ["Raster"]
    assert payload["source_authority"] == "USGS"
