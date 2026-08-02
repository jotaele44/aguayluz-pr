import csv
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_local_hydro_assets import discover, inspect_file, iter_csv, iter_geojson, merge  # noqa: E402
from build_water_relationship_graph import build_graph  # noqa: E402


def test_prasa_csv_maps_to_water_asset(tmp_path):
    p = tmp_path / "PRASA_Intakes_Outfalls_v1.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "municipality", "lat", "lon"])
        w.writeheader()
        w.writerow({"id": "A1", "name": "Intake A", "municipality": "Ponce", "lat": "18.01", "lon": "-66.61"})
    row = list(iter_csv(p, ("water", "intake_outfall", "point", "PRASA")))[0]
    assert row["asset_type"] == "water"
    assert row["asset_subtype"] == "intake_outfall"
    assert row["operator"] == "PRASA"
    assert row["review_status"] == "accepted"


def test_nid_geojson_maps_to_dam(tmp_path):
    p = tmp_path / "NID_AUTH_MASTER.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"NIDID": "PR001", "dam_name": "Dam One", "county": "Ponce"}, "geometry": {"type": "Point", "coordinates": [-66.6, 18.0]}}]}), encoding="utf-8")
    row = list(iter_geojson(p, "NID", "dam"))[0]
    assert row["asset_subtype"] == "dam"
    assert row["geometry_type"] == "point"
    assert row["lat"] == 18.0


def test_merge_is_idempotent():
    existing = [{"asset_id": "A", "asset_name": "old"}]
    out = merge(existing, [{"asset_id": "A", "asset_name": "new"}, {"asset_id": "B", "asset_name": "b"}])
    assert {r["asset_id"] for r in out} == {"A", "B"}
    assert [r for r in out if r["asset_id"] == "A"][0]["asset_name"] == "new"


def test_relationship_graph_and_risk_generation():
    assets = [
        {"asset_id": "T1", "asset_type": "water", "asset_subtype": "treatment_plant", "municipality": "Ponce"},
        {"asset_id": "P1", "asset_type": "water", "asset_subtype": "pump_station", "municipality": "Ponce"},
        {"asset_id": "D1", "asset_type": "water", "asset_subtype": "dam", "municipality": "Ponce"},
    ]
    events = [{"event_id": "AYL_EVT_20260101_X", "event_type": "water_quality_violation", "affected_area": "Ponce", "municipality": "Ponce", "source_ref": "SDWIS"}]
    rels, risks = build_graph(assets, events)
    assert any(r["predicate"] == "feeds_or_supports" for r in rels)
    assert risks and risks[0]["risk_type"] == "water_continuity"


def test_discover_extracts_zip_and_inspects_csv(tmp_path):
    src_csv = tmp_path / "PRASA_Intakes_Outfalls_v1.csv"
    src_csv.write_text("id,name,municipality,lat,lon\nA1,Intake A,Ponce,18.01,-66.61\n", encoding="utf-8")
    archive = tmp_path / "hydro.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(src_csv, arcname="Acueductos/PRASA_Intakes_Outfalls_v1.csv")
    files, report = discover([archive], tmp_path / "extract")
    assert report[0]["status"] == "zip"
    assert any(path.name == "PRASA_Intakes_Outfalls_v1.csv" for path in files)
    inspected = [inspect_file(path) for path in files if path.name == "PRASA_Intakes_Outfalls_v1.csv"][0]
    assert inspected["recognized"] is True
    assert inspected["row_count"] == 1
