import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dedup_power_assets import asset_class, build_clusters, haversine_m, source_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "asset_crosswalk.schema.json").read_text())

# HIFLD plant (coords) + EIA twin (coordless, same code) + a far OSM plant;
# a HIFLD substation + a near OSM substation; a lone Spiderweb plant far away.
ASSETS = [
    {"asset_id": "HIFLD_PP_61014", "asset_type": "power", "asset_subtype": "generation (WND)",
     "evidence_tier": "T1", "lat": 17.9876, "lon": -66.4303},
    {"asset_id": "EIA_PLANT_61014", "asset_type": "power", "asset_subtype": "generation (Wind)",
     "evidence_tier": "T1"},  # coordless EIA twin
    {"asset_id": "OSMP_-17091033", "asset_type": "power", "asset_subtype": "generation (wind)",
     "evidence_tier": "T3", "lat": 17.9878, "lon": -66.4301},  # ~25 m from HIFLD → same farm
    {"asset_id": "HIFLD_SS_SS1", "asset_type": "power", "asset_subtype": "substation (230kV)",
     "evidence_tier": "T1", "lat": 18.3989, "lon": -66.155},
    {"asset_id": "OSMS_900", "asset_type": "power", "asset_subtype": "substation",
     "evidence_tier": "T3", "lat": 18.3990, "lon": -66.1551},  # ~15 m → same substation
    {"asset_id": "PWR00099", "asset_type": "power", "asset_subtype": "Generation (Coal)",
     "evidence_tier": "T1", "lat": 18.20, "lon": -66.99},  # isolated → no cluster
    {"asset_id": "USGS_50059000", "asset_type": "water", "asset_subtype": "reservoir"},  # ignored
]


def test_helpers():
    assert source_of("HIFLD_PP_1") == "HIFLD"
    assert source_of("EIA_PLANT_2") == "EIA"
    assert source_of("OSMS_3") == "OSM"
    assert source_of("PWR00001") == "Spiderweb"
    assert asset_class({"asset_subtype": "generation (wind)"}) == "generation"
    assert 20 < haversine_m((17.9876, -66.4303), (17.9878, -66.4301)) < 40


def test_clusters_plant_code_and_proximity():
    power = [a for a in ASSETS if a["asset_type"] == "power"]
    clusters = {c["canonical_asset_id"]: c for c in build_clusters(power, 800, 400)}
    # plant cluster: HIFLD + EIA (code) + OSM (proximity) → canonical HIFLD (T1+coords)
    pc = clusters["HIFLD_PP_61014"]
    assert set(pc["member_asset_ids"]) == {"HIFLD_PP_61014", "EIA_PLANT_61014", "OSMP_-17091033"}
    assert pc["match_method"] == "plant_code+proximity"
    assert pc["asset_class"] == "generation"
    # substation cluster: HIFLD + OSM by proximity → canonical HIFLD
    ss = clusters["HIFLD_SS_SS1"]
    assert set(ss["member_asset_ids"]) == {"HIFLD_SS_SS1", "OSMS_900"}
    assert ss["match_method"] == "proximity"
    # isolated Spiderweb plant is not in any cluster
    assert "PWR00099" not in clusters
    assert all("PWR00099" not in c["member_asset_ids"] for c in clusters.values())


def test_canonical_prefers_coords_for_coordless_eia():
    power = [a for a in ASSETS if a["asset_type"] == "power"]
    pc = {c["canonical_asset_id"]: c for c in build_clusters(power, 800, 400)}["HIFLD_PP_61014"]
    canon = [m for m in pc["members"] if m["asset_id"] == pc["canonical_asset_id"]][0]
    assert canon["source"] == "HIFLD" and canon["lat"] is not None  # not the coordless EIA twin


def test_output_validates_against_schema():
    import re
    power = [a for a in ASSETS if a["asset_type"] == "power"]
    clusters = build_clusters(power, 800, 400)
    req = set(SCHEMA["required"])
    allowed = set(SCHEMA["properties"])
    pat = re.compile(SCHEMA["properties"]["cluster_id"]["pattern"])
    for c in clusters:
        assert req <= set(c) and set(c) <= allowed
        assert pat.match(c["cluster_id"])
        assert len(c["member_asset_ids"]) >= 2
        for m in c["members"]:
            assert set(m) <= {"asset_id", "source", "evidence_tier", "lat", "lon"}


def test_same_source_never_merged():
    # two distinct HIFLD substations 10 m apart must NOT merge (same source).
    power = [
        {"asset_id": "HIFLD_SS_A", "asset_type": "power", "asset_subtype": "substation",
         "evidence_tier": "T1", "lat": 18.0, "lon": -66.0},
        {"asset_id": "HIFLD_SS_B", "asset_type": "power", "asset_subtype": "substation",
         "evidence_tier": "T1", "lat": 18.00005, "lon": -66.0},
    ]
    assert build_clusters(power, 800, 400) == []
