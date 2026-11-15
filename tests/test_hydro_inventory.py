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
FEATURES = hi.read_jsonl(HYDRO / hi.FEATURES_FILE)
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
    assert RECEIPT["phase_scope"]["feature_types_enumerated"] == ["aquifer", "well"]
    for key, ledger in RECEIPT["source_ledgers"].items():
        assert ledger["state"] == "PASS" and ledger["delta"] == 0, key
        assert ledger["assigned_to_features"] == ledger["retained"], key


def test_coverage_is_a_range_and_counts_match_the_files():
    for kind in ("aquifer", "well"):
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
