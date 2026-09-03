"""Telemetry, incident, work-order, and field-result projection."""
from __future__ import annotations

from typing import Any

from .contracts import SCHEMA_OBSERVATION, stable_id, unique, validate_observation
from .operational_adapter_contracts import (
    AUTHORITATIVE_STATES,
    FIELD_METRICS,
    METRIC_BY_KIND,
    OBSERVATION_KINDS,
    OperationalAdapterError,
    _required_text,
)


class OperationalObservationMixin:
    def _materialize_observations(
        self,
        records: list[dict[str, Any]],
        asset_aliases: dict[str, str],
        edge_aliases: dict[str, str],
        graph: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        output: list[dict[str, Any]] = []
        blockers: list[str] = []
        asset_ids = {item["asset_id"] for item in graph["assets"]}
        edge_ids = {item["edge_id"] for item in graph["edges"]}
        for record in records:
            if record["input_kind"] not in OBSERVATION_KINDS:
                continue
            try:
                observation = self._adapt_observation(
                    record,
                    asset_aliases=asset_aliases,
                    edge_aliases=edge_aliases,
                )
            except OperationalAdapterError as exc:
                blockers.append(f"observation_rejected:{record['input_id']}:{exc}")
                continue
            if (
                observation.get("asset_id") not in asset_ids
                and observation.get("edge_id") not in edge_ids
            ):
                blockers.append(f"observation_target_unresolved:{record['input_id']}")
                continue
            try:
                validate_observation(
                    observation,
                    graph,
                    self.control_plane.default_max_age_seconds,
                )
            except ValueError as exc:
                blockers.append(
                    f"observation_contract_rejected:{record['input_id']}:{exc}"
                )
                continue
            output.append(observation)
        output.sort(key=lambda item: item["observation_id"])
        return output, unique(blockers)

    def _adapt_observation(
        self,
        record: dict[str, Any],
        *,
        asset_aliases: dict[str, str],
        edge_aliases: dict[str, str],
    ) -> dict[str, Any]:
        payload = record["payload"]
        kind = record["input_kind"]
        target_type = str(payload.get("target_type") or "asset")
        target_ref = _required_text(payload, "target_ref")
        asset_id = asset_aliases.get(target_ref) if target_type == "asset" else None
        edge_id = edge_aliases.get(target_ref) if target_type == "edge" else None
        if bool(asset_id) == bool(edge_id):
            raise OperationalAdapterError("operational_observation_target_unresolved")

        metric = METRIC_BY_KIND.get(kind)
        assertion = str(payload.get("assertion") or "measurement")
        field_confirmed = False
        if kind == "field_result":
            metric = FIELD_METRICS.get(assertion)
            if metric is None:
                raise OperationalAdapterError("unsupported_field_result_assertion")
            field_confirmed = (
                record["authority"] in AUTHORITATIVE_STATES
                and record["evidence_tier"] == "T1"
                and record["quality"] == "valid"
                and record["review_status"] == "accepted"
            )
        if metric is None:
            raise OperationalAdapterError("unsupported_operational_metric")

        authoritative = (
            record["authority"] in AUTHORITATIVE_STATES
            and record["evidence_tier"] == "T1"
            and record["authority"] != "synthetic_fixture"
        )
        related = []
        for reference in payload.get("related_asset_refs", []):
            resolved = asset_aliases.get(str(reference))
            if resolved:
                related.append(resolved)
        max_age = payload.get("max_age_seconds", 900)
        if not isinstance(max_age, int) or max_age <= 0:
            raise OperationalAdapterError("max_age_seconds_must_be_positive_integer")
        if record["freshness"] == "stale":
            max_age = 1
        uncertainty = payload.get("uncertainty", 0.0)
        if (
            isinstance(uncertainty, bool)
            or not isinstance(uncertainty, (int, float))
            or uncertainty < 0
        ):
            raise OperationalAdapterError("uncertainty_must_be_nonnegative_number")
        observation = {
            "schema_version": SCHEMA_OBSERVATION,
            "observation_id": str(
                payload.get("observation_id")
                or stable_id(
                    "AYL_OPOBS",
                    [record["source_id"], record["input_id"], record["sha256"]],
                )
            ),
            "observed_at": record["observed_at"],
            "source_id": record["source_id"],
            "source_kind": "offline_operational_adapter",
            "metric": metric,
            "value": payload.get("value"),
            "unit": payload.get("unit"),
            "expected_value": payload.get("expected_value"),
            "tolerance": payload.get("tolerance"),
            "uncertainty": float(uncertainty),
            "max_age_seconds": max_age,
            "evidence_tier": record["evidence_tier"],
            "authoritative": authoritative,
            "field_confirmed": field_confirmed,
            "assertion": assertion,
            "review_status": record["review_status"],
            "quality": record["quality"],
            "related_asset_ids": unique(related),
            "notes": {
                "received_at": record["received_at"],
                "source_payload_sha256": record["sha256"],
                "freshness": record["freshness"],
                "disclosure": record["disclosure"],
                "authority": record["authority"],
                "offline_only": True,
                "synthetic_fixture": record["authority"] == "synthetic_fixture",
            },
        }
        if asset_id:
            observation["asset_id"] = asset_id
        else:
            observation["edge_id"] = edge_id
        return observation
