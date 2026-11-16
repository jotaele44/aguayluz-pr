"""aguayluz.hydro_inventory: identity rules, geometry, ledgers, and the committed inventory.

The committed-inventory tests read data/hydro/ as built from the real sources. Cases that
need shapes the sources do not happen to contain (a hole in a polygon, a coordinate
disagreement, an unbalanced ledger) are CONSTRUCTED and say so.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from aguayluz import hydro_inventory as hi

REPO = Path(__file__).resolve().parent.parent
HYDRO = REPO / "data" / "hydro"
FEATURES = [f for p in sorted(HYDRO.glob(hi.FEATURES_FILE.format("*"))) for f in hi.read_jsonl(p)]
LINKS = hi.read_jsonl(HYDRO / hi.LINKS_FILE)
CONFLICTS = hi.read_jsonl(HYDRO / hi.CONFLICTS_FILE)
RECEIPT = json.loads((HYDRO / hi.RECEIPT_FILE).read_text(encoding="utf-8"))
BY_ID = {f["feature_id"]: f for f in FEATURES}

_SPEC = importlib.util.spec_from_file_location("build_hydro_inventory", REPO / "scripts" / "build_hydro_inventory.py")
build = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = build
_SPEC.loader.exec_module(build)


# ── name rules: discovery signals, never identity ─────────────────────────────
def test_names_are_compared_by_containment_not_overlap():
    assert not hi.names_compatible("Toa Baja", "Toa Alta")
    assert hi.names_compatible("PAJUIL", "PAJUIL 3 WELL, HATILLO, PR")


def test_numbers_distinguish_wells_and_roman_numerals_read_as_numbers():
    assert not hi.names_compatible("ZANJA 4 WELL", "ZANJA V")
    assert hi.names_compatible("ZANJA V", "ZANJA 5")
    assert not hi.names_compatible("CABO ROJO I", "CABO ROJO II", frozenset({"CABO", "ROJO"}))


def test_shared_municipio_words_do_not_make_names_compatible():
    stop = frozenset({"GUANICA"})
    assert hi.names_compatible("GUANICA", "SECO WELL, GUANICA")  # without the stop list
    assert not hi.names_compatible("GUANICA", "SECO WELL, GUANICA", stop)


def test_road_addresses_are_not_names_and_eqb_names_come_from_the_identifier():
    feature = {"feature_id": "WELL:WQP:PREQB_GW-CABO ROJO II", "display_name": "ROAD #103 KM 3.8 CABO ROJO"}
    assert hi.well_names(feature) == ["CABO ROJO II"]
    numeric = {"feature_id": "WELL:WQP:PREQB_GW-1757290661555", "display_name": "MAR NEGRO (RD. 703 KM. 1.5)"}
    assert hi.well_names(numeric) == []


# ── geometry ──────────────────────────────────────────────────────────────────
def test_point_in_polygon_respects_holes():
    # CONSTRUCTED: a square with a square hole.
    square = {"type": "Feature", "properties": {"group_key": "G"},
              "geometry": {"type": "Polygon", "coordinates": [
                  [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}}
    index = hi.PolygonIndex([square])
    assert index.containing(0.5, 0.5) and not index.containing(2, 2) and not index.containing(5, 5)


# ── claims and ledgers ────────────────────────────────────────────────────────
def test_claims_round_trip_through_the_compact_file(tmp_path):
    claims = [hi.claim(source_key="s", authority="A", feature_type="well", source_feature_id=str(i), name_raw=f"W{i}",
                       evidence_tier="T1", manifestation_sha256="ab" * 32, retrieved_utc="2026-11-15T00:00:00Z",
                       lat=18.1 + i / 100, lon=-66.1, attributes={"k": i}) for i in range(3)]
    claims.append(hi.claim(source_key="s", authority="A", feature_type="well", source_feature_id="x", name_raw=None,
                           evidence_tier="T1", manifestation_sha256="cd" * 32, retrieved_utc="2026-11-15T00:00:00Z",
                           disposition="EXCLUDED", exclusion_reason="test row"))
    path = tmp_path / "claims_s.jsonl"
    hi.write_claims(path, claims)
    assert sorted(hi.read_claims(path), key=lambda c: c["claim_id"]) == sorted(claims, key=lambda c: c["claim_id"])


def test_a_ledger_that_does_not_close_stops_the_run():
    assert hi.close_ledger(source_rows=5, retained=3, excluded={"r": 2}, unresolved=0)["state"] == "PASS"
    with pytest.raises(ValueError, match="does not close"):
        hi.close_ledger(source_rows=5, retained=3, excluded={"r": 1}, unresolved=0)


def test_only_i4_candidates_narrow_the_range():
    nodes = ["a", "b", "c"]
    links = [hi.link("CANDIDATE_SAME_FEATURE", "a", "b", "CANDIDATE", ["PROXIMITY_ONLY"], tier="I5"),
             hi.link("CODED_WELLS_WITHIN_POLYGON", "b", "c", "DERIVED_TOPOLOGICAL", ["CODED_WELLS_INSIDE"])]
    assert hi.component_count(nodes, links) == 3
    links.append(hi.link("CANDIDATE_SAME_FEATURE", "a", "c", "CANDIDATE", ["NORMALIZED_NAME", "PROXIMITY"], tier="I4"))
    assert hi.component_count(nodes, links) == 2


def test_the_same_usgs_site_merges_and_a_coordinate_disagreement_is_kept():
    # CONSTRUCTED: one USGS site seen by the Water Data API and by WQP, 300 m apart.
    usgs = hi.claim(source_key="usgs_monitoring_locations", authority="USGS", feature_type="well",
                    source_feature_id="180000066000000", name_raw="X WELL", evidence_tier="T1",
                    manifestation_sha256="a" * 64, retrieved_utc="t", lat=18.0, lon=-66.0,
                    attributes={"site_type_code": "GW"})
    wqp = hi.claim(source_key="wqp_wells", authority="WQP:USGS-PR", feature_type="well",
                   source_feature_id="USGS-180000066000000", name_raw="X WELL", evidence_tier="T2",
                   manifestation_sha256="b" * 64, retrieved_utc="t", lat=18.0027, lon=-66.0,
                   attributes={"usgs_site_no": "180000066000000"})
    features, conflicts = hi.build_wells([usgs], [wqp], [], {"180000066000000": ["USGSGW_180000066000000"]})
    assert len(features) == 1 and features[0]["identity_evidence"][0]["tier"] == "I1"
    assert features[0]["location_source"] == "usgs_monitoring_locations"
    assert len(conflicts) == 1 and conflicts[0]["kind"] == "coordinate"


def test_monitoring_state_distinguishes_absent_readings_from_no_data():
    well = {"feature_type": "well", "site_no": "1"}
    today = date(2026, 11, 15)
    assert hi.monitoring_state(well, None, today)["state"] == "READINGS_ABSENT_ON_SERVER"
    assert hi.monitoring_state(well, {}, today)["state"] == "NO_DATA"
    assert hi.monitoring_state(well, {"1": "2026-10-01"}, today)["state"] == "MONITORED_NOW"
    assert hi.monitoring_state(well, {"1": "2020-01-01"}, today)["state"] == "HISTORICAL_ONLY"


# ── the committed inventory ───────────────────────────────────────────────────
def test_committed_inventory_is_exactly_what_its_claims_build():
    assert build.main(["--check"]) == 0


def test_every_source_ledger_closes_and_nothing_claims_completeness():
    assert RECEIPT["completeness_claimed"] is False
    assert RECEIPT["phase_scope"]["feature_types_enumerated"] == list(hi.FEATURE_TYPES)
    assert RECEIPT["phase_scope"]["feature_types_not_enumerated"] == []
    for key, ledger in RECEIPT["source_ledgers"].items():
        assert ledger["state"] == "PASS" and ledger["delta"] == 0, key
        assert ledger["assigned_to_features"] == ledger["retained"], key


def test_coverage_is_a_range_and_counts_match_the_files():
    for kind in hi.FEATURE_TYPES:
        cov = RECEIPT["coverage"][kind]
        assert cov["features_lower"] <= cov["features_upper"]
        assert cov["features_upper"] == sum(1 for f in FEATURES if f["feature_type"] == kind)
    assert RECEIPT["coverage"]["well"]["unlocated"] == sum(1 for f in FEATURES if f["feature_id"].startswith("WELL:SDWIS:"))


def test_every_usgs_groundwater_site_is_a_feature():
    sites = RECEIPT["stage_receipts"]["sites"]["ledgers"]["usgs_monitoring_locations"]
    gw = sum(n for t, n in sites["by_site_type"].items() if t in hi.GW_SITE_TYPES)
    assert gw == sum(1 for f in FEATURES if f["feature_id"].startswith("WELL:USGS:"))
    assert sites["cross_check"]["only_legacy"] == sites["cross_check"]["only_api"] == 0


def test_name_matches_never_merge_and_upper_and_lower_ncl_stay_apart():
    for lk in LINKS:
        if lk["link_type"] == "CANDIDATE_SAME_FEATURE":
            assert lk["adjudication_state"] == "CANDIDATE_NOT_IDENTITY"
            assert lk["identity_tier"] in ("I4", "I5")
    assert not any(lk["link_type"] == "CANDIDATE_SAME_FEATURE" and {lk["from"], lk["to"]} ==
                   {"AQ:HA730:4191:main", "AQ:HA730:4192:main"} for lk in LINKS)


def test_south_coast_coded_wells_fall_in_the_south_coast_polygon():
    # An independent check on the datum: USGS codes these wells to the South Coast aquifer.
    crosstab = RECEIPT["spatial"]["aquifer_code_by_polygon_class"]["110SCPL"]
    assert crosstab.get("114", 0) / sum(crosstab.values()) > 0.9


def test_source_disagreements_are_shown_not_resolved():
    by_attr = {c["attribute"]: c for c in CONFLICTS}
    for attribute in ("south_coast_aquifer_units", "aquifer_existence", "north_coast_area"):
        assert by_attr[attribute]["resolution"] == "UNRESOLVED_SHOWN"
        assert len(by_attr[attribute]["values_by_claim"]) >= 2
    datum = by_attr["horizontal_datum"]
    assert datum["resolution"] == "RESOLVED_BY_MEASURED_FIT"
    nad27, pr40 = datum["values_by_claim"]
    assert pr40["coastline_median_m"] < 100 < nad27["coastline_median_m"]


def test_unlocated_sdwis_wells_are_listed_but_never_placed_or_bound_by_polygon():
    sdwis = [f for f in FEATURES if f["feature_id"].startswith("WELL:SDWIS:")]
    assert sdwis and all(f["lat"] is None for f in sdwis)
    ids = {f["feature_id"] for f in sdwis}
    assert not any(lk["from"] in ids and lk["edge_class"] == "DERIVED_TOPOLOGICAL" for lk in LINKS)


def test_aquifer_features_cover_every_source_and_carry_member_counts():
    aquifers = [f for f in FEATURES if f["feature_type"] == "aquifer"]
    assert {s for f in aquifers for s in f["sources"]} == {
        "usgs_ha730_aquifers_pr", "usgs_aquifer_codes", "usgs_national_aquifer_codes", "usgs_ha730_text",
        "drna_pira_2016"}
    assert BY_ID["AQ:USGS_AQFR:110SCPL"]["member_wells"]["AUTHORITATIVE"] == 145
    assert {"AQ:HA730:4191:main", "AQ:HA730:4192:main", "AQ:HA730:114:main"} <= set(BY_ID)
    assert all(f["island"] in ("main", "vieques", "culebra") for f in aquifers if f["feature_id"].startswith("AQ:HA730:"))


def test_every_usgs_spring_and_every_gnis_spring_is_a_feature_and_none_merge_on_names():
    sites = RECEIPT["stage_receipts"]["sites"]["ledgers"]["usgs_monitoring_locations"]["by_site_type"]
    springs = [f for f in FEATURES if f["feature_type"] == "spring"]
    assert sum(1 for f in springs if f["feature_id"].startswith("SPRING:USGS:")) == sites["SP"]
    gnis = RECEIPT["stage_receipts"]["names"]["ledgers"]["usgs_gnis_names"]["retained_by_class"]["Spring"]
    assert sum(1 for f in springs if f["feature_id"].startswith("SPRING:GNIS:")) == gnis
    # every spring with a published location is placed; SDWIS springs have none and are never placed
    assert all(f["located"] for f in springs if not f["feature_id"].startswith("SPRING:SDWIS:"))
    assert not any(f["located"] for f in springs if f["feature_id"].startswith("SPRING:SDWIS:"))
    assert RECEIPT["coverage"]["spring"]["features_upper"] == len(springs)


def test_every_mapped_reach_is_a_stream_and_only_coastline_is_excluded():
    ledger = RECEIPT["source_ledgers"]["usgs_nhd_flowlines"]
    assert ledger["excluded_by_reason"] == {"coastline, not a watercourse": ledger["excluded"]}
    streams = sum(1 for f in FEATURES if f["feature_type"] == "stream")
    canals = [f for f in FEATURES if f["feature_type"] == "canal"]
    # NHD canal/ditch reaches (FType 336) are listed as canals; every other retained reach is a stream
    assert streams + len(canals) == ledger["retained"] > 15000
    assert canals and all(f["feature_id"].startswith("CANAL:NHD:") and f["flow_type"] == "canal/ditch" for f in canals)
    for path in HYDRO.glob(hi.FEATURES_FILE.format("*")):
        assert path.stat().st_size < 5_000_000, path.name


def test_reaches_join_watercourses_only_on_the_gnis_id_nhd_publishes():
    reach_links = [lk for lk in LINKS if lk["link_type"] == "REACH_OF_WATERCOURSE"]
    assert reach_links and all(lk["identity_tier"] == "I2" and lk["edge_class"] == "AUTHORITATIVE" for lk in reach_links)
    for lk in reach_links[:200]:
        assert BY_ID[lk["from"]]["gnis_id"] == lk["to"].rsplit(":", 1)[1]
    assert RECEIPT["surface"]["nhd_gnis_ids_without_gnis_record"] <= 5


def test_nws_gauges_merge_with_usgs_sites_on_the_usgs_id_they_publish():
    merged = [f for f in FEATURES if f["feature_type"] == "gauge" and set(f["sources"]) == {"noaa_nwps_gauges", "usgs_monitoring_locations"}]
    assert len(merged) >= 100 and all(f["identity_evidence"][0]["tier"] == "I2" for f in merged)


def test_waterbody_kind_disagreements_are_kept():
    kinds = [c for c in CONFLICTS if c["attribute"] == "waterbody_kind"]
    assert kinds and all(c["resolution"] == "UNRESOLVED_SHOWN" for c in kinds)


def test_unlocated_intakes_are_listed_and_never_placed():
    intakes = [f for f in FEATURES if f["feature_type"] == "intake"]
    sdwis = [f for f in intakes if f["feature_id"].startswith("INTAKE:SDWIS:")]
    assert len(sdwis) == RECEIPT["source_ledgers"]["epa_sdwis_intakes"]["retained"]
    assert all(f["lat"] is None and "huc10" not in f for f in sdwis)


# ── aquifer-level series (rows CONSTRUCTED) ───────────────────────────────────
def _rows(site, values_by_month, provisional=False, param="72019"):
    return [{"site_no": site, "metric": "groundwater_level", "parameter_code": param, "unit": "ft",
             "value": v, "observed_date": f"{m}-15", "provisional": provisional} for m, v in values_by_month.items()]


def _history(site, base, years=range(2015, 2021), month="03"):
    return {f"{y}-{month}": base + (y - 2015) * 0.1 for y in years}


def test_series_uses_each_wells_own_baseline_and_needs_three_wells():
    rows = []
    for site, base in (("A", 10.0), ("B", 50.0), ("C", 30.0)):
        rows += _rows(site, _history(site, base))
        rows += _rows(site, {"2024-03": base + 2.0})        # two feet deeper than its own March
    rows += _rows("A", {"2024-03": 99.0}, param="62610")    # level above datum: must be ignored
    monthly, skipped = hi.monthly_by_well(rows, {"A", "B", "C"})
    assert skipped["other_parameter_code"] == 1
    series = hi.aquifer_series(monthly, {"A": "USGS_AQUIFER_CODE", "B": "USGS_AQUIFER_CODE", "C": "USGS_AQUIFER_CODE"})
    last = series["points"][-1]
    assert last["month"] == "2024-03" and last["n"] == 3
    # Baseline is the median of the well's whole approved record for March: offsets 0.0-0.5 and 2.0 -> 0.3.
    assert abs(last["median_ft"] - 1.7) < 1e-9
    two = hi.aquifer_series(monthly, {"A": "USGS_AQUIFER_CODE", "B": "USGS_AQUIFER_CODE"})
    assert two["points"][-1]["median_ft"] is None and two["points"][-1]["insufficient"]


def test_a_well_with_fewer_than_five_years_has_no_baseline_and_provisional_months_stay_separate():
    rows = _rows("A", _history("A", 10.0, years=range(2018, 2022)))           # four years only
    rows += _rows("B", _history("B", 20.0)) + _rows("B", {"2024-03": 21.0}, provisional=True)
    monthly, _ = hi.monthly_by_well(rows, {"A", "B"})
    series = hi.aquifer_series(monthly, {"A": "USGS_AQUIFER_CODE", "B": "USGS_AQUIFER_CODE"})
    assert series["wells_without_baseline"] == 1 and series["contributing_wells"] == ["B"]
    assert [p["month"] for p in series["provisional_points"]] == ["2024-03"]
    assert "2024-03" not in [p["month"] for p in series["points"]]


def test_membership_changes_are_marked():
    rows = []
    for site in ("A", "B", "C", "D"):
        rows += _rows(site, _history(site, 10.0, years=range(2010, 2016)))
    rows += _rows("D", {"2016-03": 10.0})
    monthly, _ = hi.monthly_by_well(rows, {"A", "B", "C", "D"})
    series = hi.aquifer_series(monthly, dict.fromkeys("ABCD", "USGS_AQUIFER_CODE"))
    changes = [p["month"] for p in series["points"] if p["membership_changed"]]
    assert changes == ["2016-03"]


def test_wells_coded_to_another_aquifer_are_never_pooled():
    store = hi.InventoryStore().load(REPO / "data")
    members, excluded = hi.series_members(store, "AQ:HA730:4191:main", include_polygon=True)
    upper_codes = {BY_ID[f"WELL:USGS:{s}"].get("aquifer_code") for s, b in members.items() if b == "INSIDE_MAPPED_OUTLINE"}
    assert upper_codes == {None}
    assert excluded["coded_to_another_aquifer"] > 0
    coded, _ = hi.series_members(store, "AQ:USGS_AQFR:122NRCSU", include_polygon=False)
    assert coded and set(coded.values()) == {"USGS_AQUIFER_CODE"}


def test_every_committed_inventory_file_is_strict_json():
    # Browsers reject NaN outright; one NaN in pr_aquifers.geojson once kept every aquifer off the map.
    def reject(constant):
        raise ValueError(f"non-JSON constant {constant}")

    paths = list(HYDRO.glob("*.json*")) + list((REPO / "data" / "geo").glob("pr_*.geojson")) \
        + list((REPO / "data" / "geo" / "streams").glob("*.geojson"))
    assert len(paths) > 20
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            for line in text.splitlines():
                if line.strip():
                    json.loads(line, parse_constant=reject)
        else:
            json.loads(text, parse_constant=reject)


# ── phase 5: water infrastructure and wetlands ────────────────────────────────
def test_publishers_without_a_shared_id_never_merge():
    """PRASA, EPA (SDWIS, NPDES) and USACE publish no common facility id, so no feature holds two of them."""
    publishers = {"prasa_facilities", "epa_sdwis_wells", "epa_sdwis_intakes", "epa_sdwis_facilities", "epa_echo_potw", "usace_nid"}
    for f in FEATURES:
        assert len(publishers & set(f["sources"])) <= 1, f["feature_id"]
    cross = [lk for lk in LINKS if lk["link_type"] == "CANDIDATE_SAME_FEATURE"
             and {lk["from"].split(":")[1], lk["to"].split(":")[1]} == {"SDWIS", "PRASA"}]
    assert cross and all(lk["identity_tier"] == "I5" and lk["evidence_classes"] == ["NORMALIZED_NAME_ONLY"] for lk in cross)


def test_non_prasa_systems_join_sdwis_only_on_the_published_pwsid():
    systems = {f["feature_id"]: f for f in FEATURES if f["feature_type"] == "water_system"}
    assert len(systems) >= 200 and all(f["located"] and f["location_meaning"].startswith("one point per") for f in systems.values())
    joins = [lk for lk in LINKS if lk["link_type"] == "FACILITY_OF_SYSTEM"]
    assert joins
    for lk in joins:
        assert lk["identity_tier"] == "I1" and lk["edge_class"] == "AUTHORITATIVE"
        assert lk["from"].split(":")[2] == systems[lk["to"]]["pwsid"]
        assert BY_ID[lk["from"]]["lat"] is None  # the system point is never copied onto the facility


def test_every_nid_dam_is_listed_and_the_faast_prepa_dams_are_among_them():
    dams = [f for f in FEATURES if f["feature_type"] == "dam"]
    assert len(dams) == RECEIPT["source_ledgers"]["usace_nid"]["source"] >= 30
    names = {hi.normalize_name(f["display_name"]) for f in dams}
    # dam names in FEMA DR-4339 PREPA FAASt project sites, a discovery list, checked against the registry
    faast = ["Adjuntas", "Carite", "Coamo", "Caonillas", "Dos Bocas", "Garzas", "Guayabal", "Guayo", "Guineo", "Loco",
             "Matrullas", "Patillas", "Pellejas", "Prieto", "Vivi", "Yahuecas"]
    assert all(hi.normalize_name(f"{n} Dam") in names for n in faast)
    # the FAASt list spells it 'Luchetti'; NID publishes 'Lucchetti' (also known as Yauco Dam)
    assert hi.normalize_name("Lucchetti Dam") in names and hi.normalize_name("Luchetti Dam") not in names
    near = [lk for lk in LINKS if lk["link_type"] == "DAM_ON_RESERVOIR"]
    assert near and all(lk["edge_class"] == "CANDIDATE" and lk["distance_m"] <= hi.DAM_RESERVOIR_M for lk in near)


def test_canals_wetlands_and_facilities_are_counted_and_unplaced_ones_say_so():
    cov = RECEIPT["coverage"]
    assert cov["canal"]["features_upper"] > 2000
    assert cov["wetland"]["features_upper"] == RECEIPT["stage_receipts"]["wetlands"]["ledgers"]["usfws_nwi"]["retained_by_feature_type"]["wetland"]
    plants = [f for f in FEATURES if f["feature_type"] == "treatment_plant"]
    assert all(f["located"] == f["feature_id"].startswith("PLANT:PRASA:") for f in plants)
    for f in FEATURES:
        if f["feature_type"] == "wetland":
            assert f["name_is_source_class_only"] and f["display_name"] == f["wetland_type"]


def test_count_disagreements_between_registries_are_shown():
    by_attr = {c["attribute"]: c for c in CONFLICTS}
    for attribute in ("wastewater_plant_count", "treatment_plant_count", "reservoir_count"):
        c = by_attr[attribute]
        assert c["feature_ids"] == [] and c["resolution"] == "UNRESOLVED_SHOWN" and len(c["values_by_claim"]) >= 2
