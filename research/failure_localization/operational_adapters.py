"""Offline operational adapter orchestration for the certified shadow core."""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from .contracts import HYDRAULIC_EDGE_TYPES, parse_timestamp, stable_id, unique
from .control_plane import FailureLocalizationControlPlane
from .operational_adapter_contracts import (
    BUNDLE_SCHEMA,
    INPUT_SCHEMA,
    RUN_SCHEMA,
    OperationalAdapterError,
)
from .operational_admission import OperationalAdmissionMixin
from .operational_graph import OperationalGraphMixin
from .operational_observations import OperationalObservationMixin


class FailureLocalizationOperationalAdapters(
    OperationalAdmissionMixin,
    OperationalGraphMixin,
    OperationalObservationMixin,
):
    """Project offline operational records into the certified shadow core."""

    def __init__(
        self,
        control_plane: FailureLocalizationControlPlane,
        *,
        synthetic_fixture_mode: bool = False,
    ) -> None:
        self.control_plane = control_plane
        self.synthetic_fixture_mode = synthetic_fixture_mode
        self.offline_only = True
        self.live_polling_enabled = False
        self.notifications_enabled = False
        self.production_promotion_enabled = False
        self.automatic_control_actions_enabled = False

    def replay_bundle(
        self,
        bundle: dict[str, Any],
        *,
        as_of: str,
        system_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Validate, project, persist receipts, and run one offline replay."""
        at = parse_timestamp(as_of)
        self._validate_bundle_envelope(bundle)
        records = [copy.deepcopy(item) for item in bundle["records"]]
        admissions = [self._admit_input(item, at) for item in records]

        receipts: list[dict[str, Any]] = []
        admitted: list[dict[str, Any]] = []
        for source, admission in zip(records, admissions, strict=True):
            receipt = self._receipt(source, admission, bundle["bundle_id"], at)
            persisted = self.control_plane.store.append_idempotent(
                "operational_adapter_receipts",
                receipt,
                idempotency_key=(
                    f"{idempotency_key}:receipt:{source.get('input_id', 'missing')}"
                ),
            )
            receipts.append(persisted)
            if admission.record is not None:
                admitted.append(admission.record)

        admission_blockers = [
            f"input_{admission.status}:{source.get('input_id', 'missing')}:{reason}"
            for source, admission in zip(records, admissions, strict=True)
            if admission.status != "admitted"
            for reason in (admission.reasons or (admission.status,))
        ]
        graph_result = self._materialize_graph(admitted, bundle, at)
        blockers = [*admission_blockers, *graph_result["blockers"]]
        if graph_result["graph"] is None:
            blockers = blockers or ["no_admissible_asset_graph"]
            receipts.extend(
                self._append_blocker_receipts(
                    blockers,
                    bundle_id=bundle["bundle_id"],
                    as_of=at,
                    idempotency_key=f"{idempotency_key}:graph",
                )
            )
            run = self._fail_closed_run(
                bundle=bundle,
                as_of=at,
                receipts=receipts,
                blockers=blockers,
                maximum_grade="L0",
            )
            return self._persist_run(run, idempotency_key)

        graph = graph_result["graph"]
        try:
            graph_receipt = self.control_plane.configure_graph(
                graph,
                idempotency_key=f"{idempotency_key}:graph",
            )
        except ValueError as exc:
            blockers = [*blockers, f"graph_contract_rejected:{exc}"]
            receipts.extend(
                self._append_blocker_receipts(
                    blockers,
                    bundle_id=bundle["bundle_id"],
                    as_of=at,
                    idempotency_key=f"{idempotency_key}:contract",
                )
            )
            run = self._fail_closed_run(
                bundle=bundle,
                as_of=at,
                receipts=receipts,
                blockers=blockers,
                maximum_grade="L0",
            )
            return self._persist_run(run, idempotency_key)
        observations, observation_blockers = self._materialize_observations(
            admitted,
            graph_result["asset_aliases"],
            graph_result["edge_aliases"],
            graph,
        )
        blockers.extend(observation_blockers)
        receipts.extend(
            self._append_blocker_receipts(
                blockers,
                bundle_id=bundle["bundle_id"],
                as_of=at,
                idempotency_key=f"{idempotency_key}:materialization",
            )
        )
        for observation in observations:
            self.control_plane.ingest_observation(
                observation,
                idempotency_key=(
                    f"{idempotency_key}:observation:{observation['observation_id']}"
                ),
            )

        try:
            assessment = self.control_plane.assess(
                as_of=at.isoformat(),
                system_id=system_id,
                idempotency_key=f"{idempotency_key}:assessment",
            )
        except (KeyError, ValueError) as exc:
            blockers.append(f"assessment_fail_closed:{exc}")
            receipts.extend(
                self._append_blocker_receipts(
                    [blockers[-1]],
                    bundle_id=bundle["bundle_id"],
                    as_of=at,
                    idempotency_key=f"{idempotency_key}:assessment-failure",
                )
            )
            run = self._fail_closed_run(
                bundle=bundle,
                as_of=at,
                receipts=receipts,
                blockers=blockers,
                maximum_grade="L0",
            )
            run["graph_id"] = graph_receipt["graph_id"]
            return self._persist_run(run, idempotency_key)
        maximum_grade = self._maximum_operational_grade(graph, blockers)
        run = {
            "schema_version": RUN_SCHEMA,
            "adapter_run_id": stable_id(
                "AYL_FLAR",
                {
                    "bundle_id": bundle["bundle_id"],
                    "graph_id": graph_receipt["graph_id"],
                    "as_of": at.isoformat(),
                    "assessment_id": assessment["assessment_id"],
                },
            ),
            "bundle_id": bundle["bundle_id"],
            "as_of": at.isoformat(),
            "status": "degraded" if blockers else "admitted",
            "maximum_operational_grade": maximum_grade,
            "graph_id": graph_receipt["graph_id"],
            "assessment_id": assessment["assessment_id"],
            "assessment": assessment,
            "input_count": len(records),
            "admitted_input_count": len(admitted),
            "observation_count": len(observations),
            "receipt_ids": unique(str(item["adapter_receipt_id"]) for item in receipts),
            "blockers": unique(blockers),
            "shadow_mode": True,
            "offline_only": True,
            "operator_view_read_only": True,
            "operator_view_enabled": self.control_plane.operator_view_enabled,
            "live_polling_enabled": False,
            "notifications_enabled": False,
            "production_promotion_enabled": False,
            "automatic_control_actions": False,
            "synthetic_fixture": bool(bundle.get("synthetic_fixture")),
            "operational_claims_forbidden": bool(
                bundle.get("synthetic_fixture")
                or bundle.get("operational_claims_forbidden")
            ),
            "safety": {
                "model_output_capped_at_l3": True,
                "adapter_failures_cannot_create_exactness": True,
                "stale_inputs_do_not_support_current_diagnosis": True,
                "identifier_conflicts_are_quarantined": True,
                "missing_topology_reduces_localization": True,
                "no_live_credentials_accepted": True,
            },
        }
        return self._persist_run(run, idempotency_key)

    def _maximum_operational_grade(
        self,
        graph: dict[str, Any],
        blockers: list[str],
    ) -> str:
        assets = graph["assets"]
        hydraulic = [
            item
            for item in graph["edges"]
            if item["edge_type"] in HYDRAULIC_EDGE_TYPES
            and item["topology_state"] != "unresolved"
        ]
        if any(
            "identifier_conflict" in item or "canonical_asset_conflict" in item
            for item in blockers
        ):
            return "L0"
        if hydraulic:
            return "L3"
        if any(item.get("pressure_zone_id") for item in assets):
            return "L2"
        if any(
            item["asset_type"] in {"service_area", "source", "treatment"}
            for item in assets
        ):
            return "L1"
        return "L0"

    def _fail_closed_run(
        self,
        *,
        bundle: dict[str, Any],
        as_of: datetime,
        receipts: list[dict[str, Any]],
        blockers: list[str],
        maximum_grade: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": RUN_SCHEMA,
            "adapter_run_id": stable_id(
                "AYL_FLAR",
                [bundle["bundle_id"], as_of.isoformat(), unique(blockers)],
            ),
            "bundle_id": bundle["bundle_id"],
            "as_of": as_of.isoformat(),
            "status": "fail_closed",
            "maximum_operational_grade": maximum_grade,
            "graph_id": None,
            "assessment_id": None,
            "assessment": {
                "schema_version": "aguayluz.failure-adapter-fail-closed-assessment/v0.1",
                "localization_grade": maximum_grade,
                "hypothesis": "unknown",
                "exact_failure_claim": False,
                "required_field_tests": ["authoritative_asset_identity_reconciliation"],
            },
            "input_count": len(bundle["records"]),
            "admitted_input_count": 0,
            "observation_count": 0,
            "receipt_ids": unique(str(item["adapter_receipt_id"]) for item in receipts),
            "blockers": unique(blockers),
            "shadow_mode": True,
            "offline_only": True,
            "operator_view_read_only": True,
            "operator_view_enabled": self.control_plane.operator_view_enabled,
            "live_polling_enabled": False,
            "notifications_enabled": False,
            "production_promotion_enabled": False,
            "automatic_control_actions": False,
            "synthetic_fixture": bool(bundle.get("synthetic_fixture")),
            "operational_claims_forbidden": True,
            "safety": {
                "model_output_capped_at_l3": True,
                "adapter_failures_cannot_create_exactness": True,
                "no_live_credentials_accepted": True,
            },
        }

    def _persist_run(self, run: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self.control_plane.store.append_idempotent(
            "operational_adapter_runs",
            run,
            idempotency_key=f"{idempotency_key}:run",
        )
