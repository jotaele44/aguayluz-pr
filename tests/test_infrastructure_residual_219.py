from __future__ import annotations

import json
from pathlib import Path

from ontology.tools.audit_infrastructure_residual_219 import adjudicate, classify


def _row(
    asset_id: str,
    asset_type: str,
    subtype: str,
    source: str,
    disposition: str = "UNRESOLVED",
) -> dict[str, object]:
    return {
        "decision_id": f"D_{asset_id}",
        "legacy_asset_id": asset_id,
        "source_member": source,
        "source_row_number": None,
        "raw_asset_type": asset_type,
        "raw_asset_subtype": subtype,
        "canonical_term_id": None,
        "disposition": disposition,
        "manifestation_relation": "NONE",
        "evidence": [],
        "identity_effect": "none",
        "certification_state": "UNRESOLVED" if disposition == "UNRESOLVED" else "PASS",
    }


def test_residual_term_overlay_is_additive_and_identity_neutral() -> None:
    base = json.loads(Path("ontology/infrastructure_terms.v0.1.json").read_text(encoding="utf-8"))
    overlay = json.loads(Path("ontology/infrastructure_residual_terms.v0.1.json").read_text(encoding="utf-8"))
    base_ids = {term["term_id"] for term in base["terms"]}
    overlay_ids = [term["term_id"] for term in overlay["terms"]]
    assert len(overlay_ids) == len(set(overlay_ids)) == 13
    assert not base_ids.intersection(overlay_ids)
    assert overlay["identity_effect"] == "none"


def test_prasa_blank_header_artifacts_are_exact_ids() -> None:
    disposition, term, _ = classify(
        _row("LOCAL_e97dbd53a17113db", "water", "intake_outfall", "PRASA_Intakes_Outfalls_v1.csv")
    )
    assert disposition == "EXCLUDED_PARSER_ARTIFACT"
    assert term is None
    disposition, term, _ = classify(
        _row("LOCAL_97bcef19baf9eb01", "water", "conduit_alignment", "Conduit_Alignments_v0.csv")
    )
    assert disposition == "EXCLUDED_PARSER_ARTIFACT"
    assert term is None


def test_prasa_composite_role_stays_unresolved() -> None:
    for asset_id in ("LOCAL_9f4ce8f022d2a535", "LOCAL_04b6fd4c4e5f5920"):
        disposition, term, _ = classify(
            _row(asset_id, "water", "intake_outfall", "PRASA_Intakes_Outfalls_v1.csv")
        )
        assert disposition == "UNRESOLVED"
        assert term is None


def test_generic_osm_pump_is_not_promoted_to_ebas() -> None:
    disposition, term, reason = classify(
        _row("PMP_TEST", "water", "pumping_station", "PR_Geodata/pumping_station.geojson (OSM)")
    )
    assert disposition == "UNRESOLVED"
    assert term is None
    assert "EBAS promotion prohibited" in reason


def test_usgs_lake_is_monitoring_manifestation_not_lake_polygon() -> None:
    disposition, term, reason = classify(
        _row("USGS_TEST", "water", "lake", "USGS NWIS Site Service, site 50000000")
    )
    assert disposition == "CLASSIFIED_SOURCE_ROW"
    assert term == "AYL_TERM_SURFACE_WATER_MONITORING_SITE"
    assert "not proof of a physical lake polygon" in reason


def test_full_frozen_residual_partition_closes() -> None:
    rows: list[dict[str, object]] = []
    rows.extend(_row(f"BASE_{i}", "water", "other", "other", "CLASSIFIED_SOURCE_ROW") for i in range(5058))
    rows.extend(
        _row(f"DUP_{i}", "water", "canal_feature", "Canal_de_Riego_features_summary.csv", "DUPLICATE_DERIVED_MANIFESTATION")
        for i in range(3187)
    )
    rows.extend(_row(f"EXCL_{i}", "water", "waterworks", "other", "EXCLUDED_SOURCE_FORMAT_RESIDUE") for i in range(11))

    rows.extend(
        _row(f"GW_{i}", "water", "groundwater_well", f"USGS OGC API field-measurements, monitoring location USGS-{i}")
        for i in range(126)
    )
    rows.extend(_row(f"LAKE_{i}", "water", "lake", f"USGS NWIS Site Service, site {i}") for i in range(22))
    rows.extend(_row(f"SUB_{i}", "power", "Substation", "HIFLD Open Data") for i in range(14))
    rows.extend(_row(f"TX_{i}", "power", "Transmission Corridor", "HIFLD Open Data") for i in range(8))

    eia = [
        ("Generation (Coal)", 1),
        ("Generation (Fuel Oil)", 3),
        ("Generation (Fuel Oil/Gas)", 1),
        ("Generation (Natural Gas)", 4),
        ("Generation (Solar PV)", 2),
        ("Generation (Solar+Battery)", 1),
    ]
    for subtype, count in eia:
        rows.extend(_row(f"EIA_{subtype}_{i}", "power", subtype, "EIA Form 860 2024") for i in range(count))

    rows.extend(_row(f"TIDE_{i}", "water", "tide_gauge", f"NOAA CO-OPS station {i}") for i in range(5))
    rows.extend(_row(f"NEON_A_{i}", "water", "research_station_aquatic", f"NEON API v0 /sites/A{i}") for i in range(2))
    rows.extend(_row(f"NEON_T_{i}", "water", "research_station_terrestrial", f"NEON API v0 /sites/T{i}") for i in range(2))
    rows.append(_row("LOCAL_0080de9d6c879419", "water", "waterworks", "Waterworks_Integrated_v2.csv"))

    rows.append(_row("LOCAL_e97dbd53a17113db", "water", "intake_outfall", "PRASA_Intakes_Outfalls_v1.csv"))
    for asset_id in ("LOCAL_abd92805564f2d6f", "LOCAL_bdc213efbbc759df", "LOCAL_9cc9b5f274300ae9"):
        rows.append(_row(asset_id, "water", "intake_outfall", "PRASA_Intakes_Outfalls_v1.csv"))
    rows.append(_row("LOCAL_a8115a64f8aca2f0", "water", "intake_outfall", "PRASA_Intakes_Outfalls_v1.csv"))
    rows.append(_row("LOCAL_9f4ce8f022d2a535", "water", "intake_outfall", "PRASA_Intakes_Outfalls_v1.csv"))
    rows.append(_row("LOCAL_04b6fd4c4e5f5920", "water", "intake_outfall", "PRASA_Intakes_Outfalls_v1.csv"))
    rows.append(_row("LOCAL_97bcef19baf9eb01", "water", "conduit_alignment", "Conduit_Alignments_v0.csv"))

    rows.extend(
        _row(f"PMP_{i}", "water", "pumping_station", "PR_Geodata/pumping_station.geojson (OSM)")
        for i in range(11)
    )
    rows.extend(
        _row(f"HIST_{i}", "water", "historic_waterworks", "TresHaciendas_Corridors.geojson")
        for i in range(8)
    )

    report, output = adjudicate(rows)
    assert len(output) == 8475
    assert report["residual_explicit_state_count"] == 219
    assert report["residual_final_states"] == {
        "CLASSIFIED_SOURCE_ROW": 196,
        "EXCLUDED_PARSER_ARTIFACT": 2,
        "UNRESOLVED": 21,
    }
    assert report["primary_classified"] == 5254
    assert report["duplicate_derived_manifestations"] == 3187
    assert report["excluded"] == 13
    assert report["unresolved"] == 21
    assert report["arithmetic_pass"] is True
    assert report["physical_asset_count_claimed"] is False
