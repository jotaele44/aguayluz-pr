"""Fail-closed diagnostic functions. Model output never exceeds L3."""
from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any

from .contracts import HYDRAULIC_EDGE_TYPES, number, stable_id, state, unique


def graph_index(assets: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]]):
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for edge in edges.values():
        if edge["edge_type"] in HYDRAULIC_EDGE_TYPES and edge["topology_state"] != "unresolved":
            outgoing[edge["from_asset_id"]].append(edge)
            incoming[edge["to_asset_id"]].append(edge)
    for rows in (*incoming.values(), *outgoing.values()):
        rows.sort(key=lambda item: item["edge_id"])
    return {"assets": assets, "incoming": incoming, "outgoing": outgoing}


def downstream(start: str, index: dict[str, Any]) -> set[str]:
    seen, queue = {start}, deque([start])
    while queue:
        current = queue.popleft()
        for edge in index["outgoing"].get(current, []):
            target = edge["to_asset_id"]
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen - {start}


def latest_value(latest, kind, target, metric):
    return latest.get((kind, target, metric))


def direction(row: dict[str, Any] | None) -> str:
    if not row:
        return "missing"
    value, expected = number(row.get("value")), number(row.get("expected_value"))
    if value is None or expected is None:
        return "unknown"
    tolerance = number(row.get("tolerance")) or 0.0
    return "low" if value < expected - tolerance else "high" if value > expected + tolerance else "normal"


def mass_balance(assets, index, latest):
    output = []
    for asset_id in sorted(assets):
        incoming, outgoing = index["incoming"].get(asset_id, []), index["outgoing"].get(asset_id, [])
        if not incoming or not outgoing:
            continue
        pairs = [(edge, latest_value(latest, "edge", edge["edge_id"], "flow")) for edge in incoming + outgoing]
        missing = [edge["edge_id"] for edge, row in pairs if not row or number(row.get("value")) is None]
        evidence = unique(row["observation_id"] for _, row in pairs if row)
        if missing:
            output.append({"asset_id": asset_id, "status": "insufficient_data", "missing_flow_edge_ids": sorted(missing), "residual": None, "uncertainty": None, "evidence_observation_ids": evidence})
            continue
        in_rows = [row for _, row in pairs[:len(incoming)]]
        out_rows = [row for _, row in pairs[len(incoming):]]
        optional = [latest_value(latest, "asset", asset_id, metric) for metric in ("production", "demand", "storage_change")]
        production, demand, storage = [number(row.get("value")) if row else 0.0 for row in optional]
        inflow = sum(float(row["value"]) for row in in_rows)
        outflow = sum(float(row["value"]) for row in out_rows)
        residual = inflow + (production or 0) - outflow - (demand or 0) - (storage or 0)
        rows = [*in_rows, *out_rows, *(row for row in optional if row)]
        uncertainty = math.sqrt(sum(float(row.get("uncertainty", 0)) ** 2 for row in rows))
        tolerance = max(2 * uncertainty, 1e-9)
        status_name = "positive_unaccounted_residual" if residual > tolerance else "negative_unaccounted_residual" if residual < -tolerance else "within_uncertainty"
        output.append({
            "asset_id": asset_id, "status": status_name, "inflow": inflow,
            "production": production or 0, "outflow": outflow, "demand": demand or 0,
            "storage_change": storage or 0, "residual": residual, "uncertainty": uncertainty,
            "evidence_observation_ids": unique(row["observation_id"] for row in rows),
            "model_residual_is_not_failure_proof": True,
        })
    return output


def pressure_discontinuities(edges, latest):
    output = []
    for edge in sorted(edges.values(), key=lambda item: item["edge_id"]):
        if edge["edge_type"] not in HYDRAULIC_EDGE_TYPES:
            continue
        upstream = latest_value(latest, "asset", edge["from_asset_id"], "pressure")
        downstream_row = latest_value(latest, "asset", edge["to_asset_id"], "pressure")
        up, down = number(upstream.get("value")) if upstream else None, number(downstream_row.get("value")) if downstream_row else None
        if up is None or down is None:
            continue
        expected = float(edge["attributes"].get("expected_pressure_drop", 0))
        excess = up - down - expected
        if excess > float(edge["attributes"].get("pressure_tolerance", 5)):
            output.append({
                "edge_id": edge["edge_id"], "from_asset_id": edge["from_asset_id"],
                "to_asset_id": edge["to_asset_id"], "observed_pressure_drop": up - down,
                "expected_pressure_drop": expected, "excess_pressure_drop": excess,
                "evidence_observation_ids": [upstream["observation_id"], downstream_row["observation_id"]],
            })
    return output


def outage_clusters(assets, latest):
    grouped = defaultdict(list)
    for asset_id, asset in assets.items():
        outage = latest_value(latest, "asset", asset_id, "outage")
        restoration = latest_value(latest, "asset", asset_id, "restoration")
        if restoration and state(restoration.get("value")) in {"restored", "complete"}:
            continue
        if outage and state(outage.get("value")) in {"outage", "low_pressure", "intermittent", "no_service"}:
            grouped[(asset.get("pressure_zone_id"), asset.get("service_area_id"))].append((asset_id, outage["observation_id"]))
    return [{
        "pressure_zone_id": key[0], "service_area_id": key[1],
        "affected_asset_ids": sorted(item[0] for item in rows), "outage_count": len(rows),
        "evidence_observation_ids": sorted(item[1] for item in rows),
    } for key, rows in sorted(grouped.items(), key=lambda item: str(item[0]))]


def make_candidate(hypothesis, asset, score, support, contradictions, missing, tests, index):
    score = max(0, min(100, int(score)))
    if score < 35:
        return None
    asset_id = asset["asset_id"]
    grade = "L1" if asset["asset_type"] == "service_area" else "L2" if asset["asset_type"] == "pressure_zone" else "L3"
    segment = unique(edge["edge_id"] for edge in index["incoming"].get(asset_id, []) + index["outgoing"].get(asset_id, []))
    candidate_contradictions = list(contradictions)
    segment_edges = index["incoming"].get(asset_id, []) + index["outgoing"].get(asset_id, [])
    if any(edge["topology_state"] == "inferred" for edge in segment_edges):
        candidate_contradictions.append("candidate_segment_uses_inferred_topology")
    return {
        "candidate_id": stable_id("AYL_FLC", {"hypothesis": hypothesis, "asset": asset_id, "edges": segment}),
        "rank": 0, "hypothesis": hypothesis, "localization_grade": grade,
        "maximum_inference_grade": "L3", "target_asset_ids": [asset_id],
        "target_edge_ids": segment, "pressure_zone_ids": unique([str(asset.get("pressure_zone_id") or "")]),
        "service_area_ids": unique([str(asset.get("service_area_id") or "")]),
        "confidence": score, "supporting_evidence_ids": unique(support),
        "contradictions": unique(candidate_contradictions), "missing_telemetry": unique(missing),
        "required_field_tests": unique(tests), "exact_failure_claim": False,
        "promotion": {
            "l4_eligible": False, "l5_eligible": False,
            "l4_requires": "accepted non-stale T1 authoritative exact-asset assertion",
            "l5_requires": "accepted non-stale T1 authoritative field confirmation after L4",
        },
    }


def build_candidates(assets, index, latest, series, balances, discontinuities):
    balance_by_asset = {row["asset_id"]: row for row in balances}
    discontinuity_by_asset = defaultdict(list)
    for row in discontinuities:
        discontinuity_by_asset[row["from_asset_id"]].append(row)
        discontinuity_by_asset[row["to_asset_id"]].append(row)
    downstream_outages = {}
    for asset_id in assets:
        evidence = []
        for target in downstream(asset_id, index):
            row = latest_value(latest, "asset", target, "outage")
            restored = latest_value(latest, "asset", target, "restoration")
            if row and state(row.get("value")) in {"outage", "low_pressure", "intermittent", "no_service"} and not (restored and state(restored.get("value")) in {"restored", "complete"}):
                evidence.append(row["observation_id"])
        downstream_outages[asset_id] = unique(evidence)
    candidates = []
    for asset_id, asset in sorted(assets.items()):
        asset_type, outages = asset["asset_type"], downstream_outages[asset_id]
        assertions = [latest_value(latest, "asset", asset_id, metric) for metric in ("failure_assertion", "work_order", "field_confirmation", "acoustic_confirmation")]
        assertions = [row for row in assertions if row]
        matching = lambda values: next((row for row in assertions if state(row.get("value")) in values or state(row.get("assertion")) in values), None)
        def add(hypothesis, score, support, contradictions, missing, tests):
            item = make_candidate(hypothesis, asset, score, support, contradictions, missing, tests, index)
            if item:
                candidates.append(item)

        if asset_type in {"transmission", "distribution"}:
            score, support, contradictions, missing = 0, [], [], []
            balance = balance_by_asset.get(asset_id)
            if balance and balance["status"] == "positive_unaccounted_residual":
                score += 30; support += balance["evidence_observation_ids"]
            elif balance and balance["status"] == "insufficient_data":
                missing += [f"flow:{item}" for item in balance["missing_flow_edge_ids"]]
            else: missing.append("complete_mass_balance")
            if discontinuity_by_asset[asset_id]:
                score += 25
                for row in discontinuity_by_asset[asset_id]: support += row["evidence_observation_ids"]
            else: missing.append("upstream_downstream_pressure")
            if outages: score += min(25, 10 + 5 * len(outages)); support += outages
            else: missing.append("downstream_outage_confirmation")
            direct = matching({"main_break", "confirmed_main_break", "rupture"})
            hypothesis = "transmission_main_break" if direct else "hidden_leak_or_main_break"
            if direct: score += 35; support.append(direct["observation_id"])
            restored = latest_value(latest, "asset", asset_id, "restoration")
            if restored and state(restored.get("value")) in {"restored", "complete"}:
                score -= 25; contradictions.append("asset_or_downstream_service_reported_restored"); support.append(restored["observation_id"])
            add(hypothesis, score, support, contradictions, missing, ["acoustic_leak_survey", "field_pressure_test", "visual_excavation_check"])

        if asset_type == "pump":
            pump, power = latest_value(latest, "asset", asset_id, "pump_state"), latest_value(latest, "asset", asset_id, "power_state")
            pressure = discontinuity_by_asset[asset_id]
            score, support, contradictions, missing = 0, [], [], []
            if pump and state(pump.get("value")) in {"off", "fault", "failed", "tripped"}: score += 35; support.append(pump["observation_id"])
            else: missing.append("pump_state")
            if power and state(power.get("value")) in {"on", "available", "normal"}: score += 15; support.append(power["observation_id"])
            elif power and state(power.get("value")) in {"off", "failed", "unavailable"}: score -= 15; support.append(power["observation_id"]); contradictions.append("power_unavailable_can_explain_pump_state")
            else: missing.append("power_state")
            if pressure:
                score += 20
                for row in pressure: support += row["evidence_observation_ids"]
            else: missing.append("downstream_pressure")
            if outages: score += 15; support += outages
            direct = matching({"pump_failure", "confirmed_pump_failure"})
            if direct: score += 30; support.append(direct["observation_id"])
            add("pump_failure", score, support, contradictions, missing, ["motor_current_test", "discharge_pressure_test", "mechanical_inspection"])
            pscore, psupport, pcontra, pmissing = 0, [], [], []
            if power and state(power.get("value")) in {"off", "failed", "unavailable"}: pscore += 45; psupport.append(power["observation_id"])
            elif power and state(power.get("value")) in {"on", "available", "normal"}: pscore -= 40; psupport.append(power["observation_id"]); pcontra.append("power_reported_available")
            else: pmissing.append("power_state")
            if pump and state(pump.get("value")) in {"off", "fault", "failed", "tripped"}: pscore += 20; psupport.append(pump["observation_id"])
            if pressure:
                pscore += 15
                for row in pressure: psupport += row["evidence_observation_ids"]
            if outages: pscore += 15; psupport += outages
            direct = matching({"power_loss", "confirmed_power_loss"})
            if direct: pscore += 30; psupport.append(direct["observation_id"])
            add("power_loss_at_pumping_asset", pscore, psupport, pcontra, pmissing, ["feeder_status_check", "generator_runtime_check", "voltage_test"])

        if asset_type == "valve":
            valve = latest_value(latest, "asset", asset_id, "valve_state")
            score, support, missing = 0, [], []
            if valve and state(valve.get("value")) in {"closed", "partially_closed"}: score += 35 if asset["attributes"].get("normally_open") else 20; support.append(valve["observation_id"])
            else: missing.append("valve_state")
            if discontinuity_by_asset[asset_id]:
                score += 20
                for row in discontinuity_by_asset[asset_id]: support += row["evidence_observation_ids"]
            if outages: score += 20; support += outages
            direct = matching({"valve_misconfiguration", "confirmed_valve_error", "unexpected_valve_closure"})
            if direct: score += 30; support.append(direct["observation_id"])
            add("valve_misconfiguration_or_closure", score, support, [], missing, ["physical_valve_position_check", "control_log_review"])

        if asset_type == "tank":
            tank, history = latest_value(latest, "asset", asset_id, "tank_level"), series.get(("asset", asset_id, "tank_level"), [])
            score, support, missing = 0, [], []
            if direction(tank) == "low": score += 35; support.append(tank["observation_id"])
            else: missing.append("low_tank_level")
            if len(history) >= 2 and number(history[-1].get("value")) < number(history[-2].get("value")):
                score += 15; support += [history[-2]["observation_id"], history[-1]["observation_id"]]
            else: missing.append("tank_level_trend")
            if outages: score += 20; support += outages
            direct = matching({"tank_depletion", "confirmed_tank_depletion"})
            if direct: score += 30; support.append(direct["observation_id"])
            add("tank_depletion", score, support, [], missing, ["tank_level_gauge_check", "inlet_outlet_flow_check"])

        if asset_type == "treatment":
            production, treatment = latest_value(latest, "asset", asset_id, "production"), latest_value(latest, "asset", asset_id, "treatment_state")
            score, support, missing = 0, [], []
            if direction(production) == "low": score += 35; support.append(production["observation_id"])
            elif treatment and state(treatment.get("value")) in {"off", "failed", "limited"}: score += 35; support.append(treatment["observation_id"])
            else: missing.append("treatment_production_or_state")
            if outages: score += 20; support += outages
            direct = matching({"treatment_failure", "confirmed_treatment_failure"})
            if direct: score += 30; support.append(direct["observation_id"])
            add("treatment_failure", score, support, [], missing, ["raw_water_inflow_check", "plant_process_alarm_review", "production_meter_check"])

        if asset_type in {"source", "intake"}:
            availability = latest_value(latest, "asset", asset_id, "source_availability")
            flows = [latest_value(latest, "edge", edge["edge_id"], "flow") for edge in index["outgoing"].get(asset_id, [])]
            score, support, contradictions, missing = 0, [], [], []
            if direction(availability) == "low": score += 40; support.append(availability["observation_id"])
            elif availability: contradictions.append("source_availability_not_low"); support.append(availability["observation_id"])
            else: missing.append("source_availability")
            low = [row for row in flows if direction(row) == "low"]
            if low: score += 25; support += [row["observation_id"] for row in low]
            elif not flows: missing.append("outgoing_source_flow")
            if outages: score += min(25, 10 + 5 * len(outages)); support += outages
            add("source_water_shortage", score, support, contradictions, missing, ["source_yield_check", "intake_obstruction_check", "operator_withdrawal_review"])

        if asset_type in {"pressure_zone", "service_area"}:
            outage = latest_value(latest, "asset", asset_id, "outage")
            if outage and state(outage.get("value")) in {"outage", "low_pressure", "intermittent", "no_service"}:
                add("unresolved_service_delivery_failure", 40, [outage["observation_id"]], [], ["upstream_pressure", "upstream_flow", "pump_state", "valve_state", "tank_level"], ["pressure_logging", "valve_sweep", "customer_outage_boundary_survey"])

    deduped = {}
    for item in candidates:
        key = (item["hypothesis"], tuple(item["target_asset_ids"]))
        if key not in deduped or item["confidence"] > deduped[key]["confidence"]:
            deduped[key] = item
    ranked = sorted(deduped.values(), key=lambda item: (-item["confidence"], item["candidate_id"]))
    for rank, item in enumerate(ranked, 1): item["rank"] = rank
    return ranked
