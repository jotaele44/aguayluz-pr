"""Validate the committed PR boundary GeoJSON map layers (Census-derived)."""
import json
from pathlib import Path

from aguayluz import REPO_ROOT

MUNI = REPO_ROOT / "data/geo/pr_municipios.geojson"
BARRIOS = REPO_ROOT / "data/geo/pr_barrios.geojson"
CENTROIDS = REPO_ROOT / "data/geo/pr_municipios.json"


def _features(path: Path) -> list:
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["type"] == "FeatureCollection"
    return doc["features"]


def test_municipio_polygons():
    feats = _features(MUNI)
    assert len(feats) == 78
    for f in feats:
        assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert f["properties"]["name"] and f["properties"]["geoid"].startswith("72")


def test_barrios_link_to_municipios():
    munis = {f["properties"]["name"] for f in _features(MUNI)}
    barrios = _features(BARRIOS)
    assert len(barrios) > 800
    parents = {f["properties"]["municipio"] for f in barrios}
    assert parents <= munis  # every barrio's parent is one of the 78 municipios


def test_polygon_and_centroid_layers_share_names():
    munis = {f["properties"]["name"] for f in _features(MUNI)}
    centroids = {m["name"] for m in json.loads(CENTROIDS.read_text())["municipios"]}
    assert munis == centroids  # the two geodata files interoperate by name
