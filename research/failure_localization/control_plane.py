"""Shadow-only exact-failure localization control plane."""
from __future__ import annotations

import copy
from collections import defaultdict
from pathlib import Path
from typing import Any

from .contracts import (
    CONTROL_ASSET_TYPES, L4_ASSERTIONS, L5_ASSERTIONS, LOCALIZATION_GRADES,
    SCHEMA_ASSESSMENT, SCHEMA_GRAPH, digest, parse_timestamp, stable_id, unique,
    validate_graph, validate_observation,
)
from .diagnostics import (
    build_candidates, graph_index, mass_balance, outage_clusters,
    pressure_discontinuities,
)
from .ledger import AppendOnlyLocalizationLedger


class FailureLocalizationControlPlane:
    def __init__(self, root: Path, *, default_max_age_seconds: int = 900, operator_view_enabled: bool = False) -> None:
        if default_max_age_seconds <= 0:
            raise ValueError("default_max_age_seconds_must_be_positive")
        self.store = AppendOnlyLocalizationLedger(root)
        self.default_max_age_seconds = default_max_age_seconds
        self.operator_view_enabled = operator_view_enabled
        self.shadow_mode = True
        self.notifications_enabled = False
        self.automatic_control_actions_enabled = False
        self.production_promotion_enabled = False

    def configure_graph(self, graph: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        validated = validate_graph(graph)
        snapshot = {
            "schema_version": SCHEMA_GRAPH,
            "graph_id": graph.get("graph_id") or stable_id("AYL_FLG", validated),
            "effective_at": graph.get("effective_at"),
            **validated, "shadow_mode": True, "automatic_control_actions": False,
        }
        return self.store.append_idempotent("graph_snapshots", snapshot, idempotency_key=idempotency_key)

    def ingest_observation(self, observation: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        row = validate_observation(observation, self._graph(), self.default_max_age_seconds)
        prior = self.store.latest("observations", "observation_id", row["observation_id"])
        if prior and prior.get("payload_hash") != digest(row):
            raise ValueError("observation_id_payload_conflict")
        return self.store.append_idempotent("observations", row, idempotency_key=idempotency_key)

    def assess(self, *, as_of: str, system_id: str | None = None, idempotency_key: str) -> dict[str, Any]:
        graph, at = self._graph(), parse_timestamp(as_of)
        all_assets = {item["asset_id"]: item for item in graph["assets"]}
        assets = {key: value for key, value in all_assets.items() if system_id is None or value.get("system_id") == system_id}
        if system_id is not None and not assets:
            raise ValueError("unknown_system_id")
        edges = {item["edge_id"]: item for item in graph["edges"] if item["from_asset_id"] in assets and item["to_asset_id"] in assets}
        materialized = self._materialize_observations(at)
        index = graph_index(assets, edges)
        balances = mass_balance(assets, index, materialized["latest"])
        discontinuities = pressure_discontinuities(edges, materialized["latest"])
        clusters = outage_clusters(assets, materialized["latest"])
        candidates = build_candidates(assets, index, materialized["latest"], materialized["series"], balances, discontinuities)
        if not candidates:
            candidates = [self._unknown_candidate(assets, materialized["stale_observation_ids"])]
        seed = {
            "graph_id": graph["graph_id"], "as_of": at.isoformat(), "system_id": system_id,
            "candidates": [[item["hypothesis"], item["target_asset_ids"]] for item in candidates],
            "observations": sorted(row.get("record_hash") for row in self.store.read("observations") if row.get("record_hash")),
        }
        assessment = {
            "schema_version": SCHEMA_ASSESSMENT, "assessment_id": stable_id("AYL_FLA", seed),
            "graph_id": graph["graph_id"], "as_of": at.isoformat(), "system_id": system_id,
            "localization_grades": LOCALIZATION_GRADES, "mass_balance": balances,
            "hydraulic_discontinuities": discontinuities, "outage_clusters": clusters,
            "candidates": candidates, **{key: materialized[key] for key in (
                "stale_observation_ids", "rejected_observation_ids", "future_observation_ids"
            )},
            "shadow_mode": True, "notifications_enabled": False,
            "automatic_control_actions": False, "production_promotion_enabled": False,
            "safety": {
                "maximum_inference_grade": "L3",
                "l4_requires_authoritative_exact_asset_evidence": True,
                "l5_requires_field_confirmation": True,
                "model_residual_is_not_failure_proof": True,
                "stale_observations_do_not_support_localization": True,
            },
        }
        persisted = self.store.append_idempotent("assessments", assessment, idempotency_key=idempotency_key)
        return self._materialize_assessment(persisted["assessment_id"])

    def promote_candidate(
        self, *, assessment_id: str, candidate_id: str, requested_grade: str,
        evidence_observation_ids: list[str], reviewer: str, occurred_at: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if requested_grade not in {"L4", "L5"}:
            raise ValueError("promotion_grade_must_be_l4_or_l5")
        assessment = self._materialize_assessment(assessment_id)
        candidate = next((item for item in assessment["candidates"] if item["candidate_id"] == candidate_id), None)
        if not candidate:
            raise KeyError(candidate_id)
        required = "L3" if requested_grade == "L4" else "L4"
        if candidate["localization_grade"] != required:
            raise ValueError(f"promotion_sequence_violation:{candidate['localization_grade']}:{requested_grade}")
        at, evidence = parse_timestamp(occurred_at), self._observation_records(evidence_observation_ids)
        check = self._is_l4_evidence if requested_grade == "L4" else self._is_l5_evidence
        if not any(check(row, candidate, at) for row in evidence):
            raise ValueError("l4_authoritative_exact_asset_evidence_required" if requested_grade == "L4" else "l5_field_confirmation_required")
        event = {
            "promotion_event_id": stable_id("AYL_FLP", [assessment_id, candidate_id, requested_grade, sorted(evidence_observation_ids), reviewer]),
            "assessment_id": assessment_id, "candidate_id": candidate_id,
            "from_grade": required, "to_grade": requested_grade,
            "evidence_observation_ids": sorted(evidence_observation_ids), "reviewer": reviewer,
            "occurred_at": at.isoformat(), "append_only": True, "control_action_authorized": False,
        }
        self.store.append_idempotent("promotion_events", event, idempotency_key=idempotency_key)
        return self._materialize_assessment(assessment_id)

    def current_assessment(self, assessment_id: str, *, view_mode: str = "public") -> dict[str, Any]:
        assessment = self._materialize_assessment(assessment_id)
        if view_mode == "operator":
            if not self.operator_view_enabled:
                raise PermissionError("operator_view_disabled")
            assessment["view_mode"] = "operator"
            return assessment
        if view_mode != "public":
            raise ValueError("unknown_view_mode")
        assessment["view_mode"] = "public"
        return self._redact_public(assessment)

    def _graph(self) -> dict[str, Any]:
        rows = self.store.read("graph_snapshots")
        if not rows:
            raise ValueError("failure_localization_graph_not_configured")
        return rows[-1]

    def _materialize_observations(self, at):
        series, stale, rejected, future = defaultdict(list), [], [], []
        for row in self.store.read("observations"):
            if row["review_status"] == "rejected" or row["quality"] == "invalid":
                rejected.append(row["observation_id"]); continue
            observed = parse_timestamp(row["observed_at"])
            if observed > at:
                future.append(row["observation_id"]); continue
            if (at - observed).total_seconds() > row["max_age_seconds"]:
                stale.append(row["observation_id"]); continue
            kind, target = ("asset", row["asset_id"]) if row.get("asset_id") else ("edge", row["edge_id"])
            series[(kind, target, row["metric"])].append(row)
        latest = {}
        for key, rows in series.items():
            rows.sort(key=lambda item: parse_timestamp(item["observed_at"]))
            latest[key] = rows[-1]
        return {
            "latest": latest, "series": series, "stale_observation_ids": sorted(stale),
            "rejected_observation_ids": sorted(rejected), "future_observation_ids": sorted(future),
        }

    @staticmethod
    def _unknown_candidate(assets, stale):
        return {
            "candidate_id": stable_id("AYL_FLC", {"unknown": unique(str(item.get("system_id") or "") for item in assets.values())}),
            "rank": 1, "hypothesis": "unknown", "localization_grade": "L0",
            "maximum_inference_grade": "L3", "target_asset_ids": [], "target_edge_ids": [],
            "pressure_zone_ids": [], "service_area_ids": [], "confidence": 0,
            "supporting_evidence_ids": [],
            "contradictions": ["only_stale_observations_available"] if stale else [],
            "missing_telemetry": ["flow", "pressure", "tank_level", "pump_state", "valve_state", "power_state", "outage_boundary"],
            "required_field_tests": ["systematic_field_survey"], "exact_failure_claim": False,
            "promotion": {
                "l4_eligible": False, "l5_eligible": False,
                "l4_requires": "accepted non-stale T1 authoritative exact-asset assertion",
                "l5_requires": "accepted non-stale T1 authoritative field confirmation after L4",
            },
        }

    def _observation_records(self, ids):
        wanted = set(ids)
        found = [row for row in self.store.read("observations") if row["observation_id"] in wanted]
        if {row["observation_id"] for row in found} != wanted:
            raise ValueError("promotion_observation_not_found")
        return found

    def _current(self, row, at):
        observed = parse_timestamp(row["observed_at"])
        return observed <= at and (at - observed).total_seconds() <= row["max_age_seconds"]

    @staticmethod
    def _binds(row, candidate):
        return row.get("asset_id") in candidate["target_asset_ids"] or row.get("edge_id") in candidate["target_edge_ids"] or bool(set(row.get("related_asset_ids", [])).intersection(candidate["target_asset_ids"]))

    def _is_l4_evidence(self, row, candidate, at):
        return row["review_status"] == "accepted" and row["quality"] == "valid" and row["evidence_tier"] == "T1" and row["authoritative"] and self._current(row, at) and self._binds(row, candidate) and row["assertion"] in L4_ASSERTIONS

    def _is_l5_evidence(self, row, candidate, at):
        return row["review_status"] == "accepted" and row["quality"] == "valid" and row["evidence_tier"] == "T1" and row["authoritative"] and row["field_confirmed"] and self._current(row, at) and self._binds(row, candidate) and row["assertion"] in L5_ASSERTIONS

    def _materialize_assessment(self, assessment_id):
        base = self.store.latest("assessments", "assessment_id", assessment_id)
        if not base:
            raise KeyError(assessment_id)
        output = copy.deepcopy(base)
        events = [row for row in self.store.read("promotion_events") if row["assessment_id"] == assessment_id]
        events.sort(key=lambda item: parse_timestamp(item["occurred_at"]))
        grouped = defaultdict(list)
        for event in events: grouped[event["candidate_id"]].append(event)
        for candidate in output["candidates"]:
            history = grouped[candidate["candidate_id"]]
            candidate["promotion_history"] = history
            if history:
                candidate["localization_grade"] = history[-1]["to_grade"]
                candidate["exact_failure_claim"] = True
                candidate["promotion"]["l4_eligible"] = any(item["to_grade"] == "L4" for item in history)
                candidate["promotion"]["l5_eligible"] = any(item["to_grade"] == "L5" for item in history)
        output["promotion_events"] = events
        return output

    def _redact_public(self, assessment):
        assets = {item["asset_id"]: item for item in self._graph()["assets"]}
        for candidate in assessment["candidates"]:
            visible, count = [], 0
            for asset_id in candidate["target_asset_ids"]:
                asset = assets.get(asset_id, {})
                if asset.get("asset_type") in CONTROL_ASSET_TYPES and asset.get("disclosure") != "public_exact":
                    visible.append(stable_id("AYL_REDACTED", asset_id, 16)); count += 1
                else: visible.append(asset_id)
            if count:
                candidate["target_asset_ids"], candidate["target_edge_ids"] = visible, []
                candidate["public_redaction"] = {"redacted_control_asset_count": count, "exact_operator_details_withheld": True}
        return assessment
