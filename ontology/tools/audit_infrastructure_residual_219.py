#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def classify(row: dict[str, Any]) -> tuple[str, str | None, str]:
    aid = str(row["legacy_asset_id"])
    atype = row.get("raw_asset_type")
    subtype = row.get("raw_asset_subtype")
    source = str(row.get("source_member") or "")

    if aid == "LOCAL_97bcef19baf9eb01":
        return (
            "EXCLUDED_PARSER_ARTIFACT",
            None,
            "Recovered Conduit CSV contains only a blank physical row followed by the true header; legacy DictReader emitted the header as data.",
        )
    if aid == "LOCAL_e97dbd53a17113db":
        return (
            "EXCLUDED_PARSER_ARTIFACT",
            None,
            "Recovered PRASA intake/outfall CSV begins with a blank physical row; legacy DictReader emitted the true header as data.",
        )

    prasa: dict[str, tuple[str, str | None, str]] = {
        "LOCAL_abd92805564f2d6f": (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_SURFACE_WATER_INTAKE",
            "Recovered source row D3-001 explicitly states Facility_Type=Intake.",
        ),
        "LOCAL_bdc213efbbc759df": (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_SURFACE_WATER_INTAKE",
            "Recovered source row D3-002 explicitly states Facility_Type=Intake.",
        ),
        "LOCAL_9cc9b5f274300ae9": (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_SURFACE_WATER_INTAKE",
            "Recovered source row D3-003 explicitly states Facility_Type=Intake.",
        ),
        "LOCAL_a8115a64f8aca2f0": (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_SURFACE_WATER_OUTFALL",
            "Recovered source row D3-006 explicitly states Facility_Type=Outfall; physical facility identity remains unbound.",
        ),
        "LOCAL_9f4ce8f022d2a535": (
            "UNRESOLVED",
            None,
            "Recovered source row D3-004 explicitly retains composite Facility_Type=Intake/Outfall; opposite network roles cannot be split safely.",
        ),
        "LOCAL_04b6fd4c4e5f5920": (
            "UNRESOLVED",
            None,
            "Recovered source row D3-005 explicitly retains composite Facility_Type=Intake/Outfall; opposite network roles cannot be split safely.",
        ),
    }
    if aid in prasa:
        return prasa[aid]

    if aid == "LOCAL_0080de9d6c879419":
        return (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_WATER_QUALITY_SAMPLE_SITE",
            "Recovered Waterworks source Function explicitly states water-quality sample site.",
        )

    if (
        atype == "water"
        and subtype == "groundwater_well"
        and (
            source.startswith("USGS NWIS Site Service")
            or source.startswith("USGS OGC API field-measurements")
            or source.startswith("USGS samples-data")
        )
    ):
        return (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_GROUNDWATER_MONITORING_SITE",
            "USGS source manifestation is explicitly a groundwater monitoring/site-measurement location; no production-well function is inferred.",
        )
    if atype == "water" and subtype == "lake" and source.startswith("USGS NWIS Site Service"):
        return (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_SURFACE_WATER_MONITORING_SITE",
            "USGS NWIS row is a monitoring/site-service manifestation associated with a lake site type, not proof of a physical lake polygon.",
        )
    if atype == "water" and subtype == "tide_gauge" and source.startswith("NOAA CO-OPS station"):
        return (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_TIDE_GAUGE",
            "NOAA CO-OPS station source explicitly establishes tide-gauge monitoring function.",
        )
    if (
        atype == "water"
        and subtype in {"research_station_aquatic", "research_station_terrestrial"}
        and source.startswith("NEON API v0 /sites/")
    ):
        return (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_ENVIRONMENTAL_RESEARCH_STATION",
            "NEON /sites source explicitly establishes an environmental research-station site; aquatic/terrestrial raw subtype is preserved.",
        )

    if atype == "power" and subtype == "Substation" and source == "HIFLD Open Data":
        return (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_ELECTRIC_SUBSTATION",
            "HIFLD source class explicitly identifies an electric substation.",
        )
    if atype == "power" and subtype == "Transmission Corridor" and source == "HIFLD Open Data":
        return (
            "CLASSIFIED_SOURCE_ROW",
            "AYL_TERM_ELECTRIC_TRANSMISSION_CORRIDOR",
            "HIFLD source class explicitly identifies an electric transmission corridor; corridor representation is retained.",
        )

    eia_terms = {
        "Generation (Coal)": "AYL_TERM_COAL_GENERATION_FACILITY",
        "Generation (Fuel Oil)": "AYL_TERM_FUEL_OIL_GENERATION_FACILITY",
        "Generation (Fuel Oil/Gas)": "AYL_TERM_DUAL_FUEL_GENERATION_FACILITY",
        "Generation (Natural Gas)": "AYL_TERM_NATURAL_GAS_GENERATION_FACILITY",
        "Generation (Solar PV)": "AYL_TERM_SOLAR_PV_GENERATION_FACILITY",
        "Generation (Solar+Battery)": "AYL_TERM_SOLAR_BATTERY_GENERATION_FACILITY",
    }
    if atype == "power" and subtype in eia_terms and source.startswith("EIA Form 860"):
        return (
            "CLASSIFIED_SOURCE_ROW",
            eia_terms[subtype],
            "EIA Form 860 source class explicitly establishes generation-facility technology/fuel class; facility identity is unchanged.",
        )

    if atype == "water" and subtype == "pumping_station" and source == "PR_Geodata/pumping_station.geojson (OSM)":
        return (
            "UNRESOLVED",
            None,
            "Generic OSM pumping-station source does not distinguish potable, raw-water, wastewater, stormwater, or other pumping function; EBAS promotion prohibited.",
        )
    if atype == "water" and subtype == "historic_waterworks" and source == "TresHaciendas_Corridors.geojson":
        return (
            "UNRESOLVED",
            None,
            "Historic waterworks is an umbrella/historical manifestation; source label alone does not establish a canonical physical subtype.",
        )

    return "UNRESOLVED", None, "No exact source-specific residual rule supports a stronger state."


def adjudicate(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    unresolved_input = [row for row in rows if row.get("disposition") == "UNRESOLVED"]
    if len(rows) != 8475 or len(unresolved_input) != 219:
        raise RuntimeError(
            f"expected 8475 rows with 219 unresolved, got rows={len(rows)} unresolved={len(unresolved_input)}"
        )

    output: list[dict[str, Any]] = []
    residual_counts: Counter[str] = Counter()
    for row in rows:
        out = dict(row)
        if row.get("disposition") == "UNRESOLVED":
            disposition, term_id, reason = classify(row)
            out["disposition"] = disposition
            out["canonical_term_id"] = term_id
            out["certification_state"] = "PASS" if disposition != "UNRESOLVED" else "UNRESOLVED"
            out["identity_effect"] = "none"
            evidence = list(out.get("evidence") or [])
            evidence.append(reason)
            out["evidence"] = evidence
            out["residual_decision_id"] = (
                "AYL_RES219_" + hashlib.sha256(str(row["legacy_asset_id"]).encode()).hexdigest()[:20]
            )
            residual_counts[disposition] += 1
        output.append(out)

    counts: Counter[str] = Counter(row["disposition"] for row in output)
    primary = counts["CLASSIFIED_SOURCE_ROW"]
    duplicates = counts["DUPLICATE_DERIVED_MANIFESTATION"]
    excluded = counts["EXCLUDED_SOURCE_FORMAT_RESIDUE"] + counts["EXCLUDED_PARSER_ARTIFACT"]
    unresolved = counts["UNRESOLVED"]
    closed = primary + duplicates + excluded + unresolved
    report = {
        "source_rows": len(output),
        "input_residual_rows": 219,
        "residual_final_states": dict(sorted(residual_counts.items())),
        "residual_explicit_state_count": sum(residual_counts.values()),
        "primary_classified": primary,
        "duplicate_derived_manifestations": duplicates,
        "excluded": excluded,
        "unresolved": unresolved,
        "closed_total": closed,
        "arithmetic_pass": closed == len(output),
        "expected": {
            "source_rows": 8475,
            "primary_classified": 5254,
            "duplicate_derived_manifestations": 3187,
            "excluded": 13,
            "unresolved": 21,
        },
        "identity_effect": "none",
        "physical_asset_count_claimed": False,
        "pr_wide_exhaustion_claimed": False,
        "bounded_residual_exhaustion_claimed": True,
    }
    observed = {key: report[key] for key in report["expected"]}
    if (
        not report["arithmetic_pass"]
        or report["residual_explicit_state_count"] != 219
        or observed != report["expected"]
    ):
        raise RuntimeError(
            f"residual adjudication drift: observed={observed!r} residual={dict(residual_counts)!r}"
        )
    return report, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-decisions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    args = parser.parse_args()
    report, decisions = adjudicate(load_jsonl(args.replay_decisions))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with args.decisions.open("w", encoding="utf-8") as handle:
        for decision in decisions:
            handle.write(json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
