from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from server.backend.water_disruption import WaterIncidentService

NOW = datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc)


def observation(
    metric: str,
    value,
    *,
    observation_id: str | None = None,
    window: str = "WINDOW-1",
    observed_at: datetime = NOW,
    location_id: str = "FIELD-LC-1",
    direct_or_proxy: str | None = None,
    representativeness: str | None = None,
    historical: bool = False,
    unit: str = "ft3/s",
    qa_status: str = "accepted",
    condition: str = "unknown",
    threshold_provenance: str = "none",
):
    direct_metrics = {
        "lagoon_stage", "outflow_discharge", "groundwater_level",
        "specific_conductance", "water_temperature", "dissolved_oxygen",
        "ph", "turbidity", "nitrate", "ammonia", "phosphorus",
        "fecal_indicator",
    }
    direct = metric in direct_metrics
    return {
        "schema_version": "aguayluz.laguna-cartagena-observation/v0.2",
        "observation_id": observation_id or f"AYL_LC_OBS_{metric}_{window}",
        "observation_window_id": window,
        "observed_at": observed_at.isoformat(),
        "valid_until": (observed_at + timedelta(days=2)).isoformat(),
        "source_id": f"SRC-{metric}",
        "source_record_id": f"REC-{metric}-{window}",
        "source_hash": "a" * 64,
        "provider": "TEST SYNTHETIC FIXTURE",
        "location_id": location_id,
        "location_name": "Synthetic Laguna Cartagena test point",
        "municipality": "Lajas",
        "metric": metric,
        "value": value,
        "unit": unit,
        "evidence_tier": "T1",
        "direct_or_proxy": direct_or_proxy or ("direct" if direct else "proxy"),
        "distance_from_target_km": 0.2 if direct else 8.0,
        "hydrologic_representativeness": representativeness or ("direct" if direct else "high"),
        "historical_baseline": historical,
        "qa_status": qa_status,
        "provisional": False,
        "condition": condition,
        "threshold_provenance": threshold_provenance,
        "method": "SYNTHETIC TEST ONLY",
        "notes": "SYNTHETIC TEST FIXTURE — not an operational observation.",
        "evidence_ids": [f"EVD-{metric}"],
        "shadow_mode": True,
    }


def ingest(service: WaterIncidentService, payload: dict, key: str | None = None):
    return service.intake({"payload": payload}, key or payload["observation_id"])


def test_empty_control_plane_is_explicit_unknown(tmp_path):
    service = WaterIncidentService(tmp_path)
    summary = service.laguna_cartagena_summary(now=NOW)
    assert summary["current_condition"]["status"] == "unknown"
    assert summary["current_condition"]["direct_observation_count"] == 0
    assert "lagoon_stage" in summary["current_condition"]["missing_required_metrics"]
    assert summary["alerts_enabled"] is False
    assert summary["automatic_control_actions_enabled"] is False


def test_historical_and_guil_observations_never_become_current(tmp_path):
    service = WaterIncidentService(tmp_path)
    old = observation(
        "specific_conductance",
        2350,
        observed_at=datetime(1986, 3, 25, tzinfo=timezone.utc),
        historical=True,
        unit="uS/cm",
    )
    ingest(service, old)
    guil = observation(
        "groundwater_level",
        12.0,
        location_id="GUIL",
        unit="ft",
    )
    ingest(service, guil)
    summary = service.laguna_cartagena_summary(now=NOW)
    assert summary["current_condition"]["eligible_observation_count"] == 0
    reasons = {
        reason
        for row in summary["rejected_current_observations"]
        for reason in row["eligibility_reasons"]
    }
    assert "historical_baseline_not_current" in reasons
    assert "guil_not_lajas_groundwater_substitute" in reasons
    assert summary["preserve"]["no_guil_to_lajas_groundwater_substitution"] is True


def test_unsynchronized_operational_window_rejects_mass_balance(tmp_path):
    service = WaterIncidentService(tmp_path)
    ingest(service, observation("canal_release", 100, observed_at=NOW, unit="ft3/s"))
    ingest(service, observation(
        "treatment_withdrawal",
        25,
        observed_at=NOW - timedelta(hours=30),
        unit="ft3/s",
    ))
    ingest(service, observation(
        "agricultural_turnout",
        40,
        observed_at=NOW - timedelta(hours=30),
        unit="ft3/s",
    ))
    ingest(service, observation(
        "terminal_flow",
        20,
        observed_at=NOW - timedelta(hours=30),
        unit="ft3/s",
    ))
    summary = service.laguna_cartagena_summary(now=NOW)
    assert summary["synchronization"]["status"] == "unsynchronized"
    assert summary["water_balance"]["status"] == "not_computed"
    assert any(
        item["cause"] == "measurement_asynchrony"
        and item["state"] == "supported"
        for item in summary["hypotheses"]
    )
    assert summary["preserve"]["no_unsynchronized_mass_balance_claims"] is True


def test_synchronized_balance_separates_allocations_from_residual(tmp_path):
    service = WaterIncidentService(tmp_path)
    values = {
        "canal_release": 100,
        "treatment_withdrawal": 30,
        "agricultural_turnout": 40,
        "terminal_flow": 20,
        "known_leak_flow": 5,
    }
    for metric, value in values.items():
        ingest(service, observation(metric, value, unit="ft3/s"))
    summary = service.laguna_cartagena_summary(now=NOW)
    assert summary["synchronization"]["status"] == "synchronized"
    assert summary["water_balance"]["status"] == "balanced_within_tolerance"
    assert summary["water_balance"]["residual"] == 5
    assert summary["water_balance"]["root_cause_claim"] is None
    assert any(
        item["cause"] == "allocated_withdrawal"
        and item["state"] == "supported"
        for item in summary["hypotheses"]
    )
    assert not any(
        item["cause"] == "conveyance_loss"
        for item in summary["hypotheses"]
    )


def test_unexplained_residual_is_candidate_not_confirmed(tmp_path):
    service = WaterIncidentService(tmp_path)
    values = {
        "canal_release": 100,
        "treatment_withdrawal": 20,
        "agricultural_turnout": 20,
        "terminal_flow": 10,
    }
    for metric, value in values.items():
        ingest(service, observation(metric, value, unit="ft3/s"))
    summary = service.laguna_cartagena_summary(now=NOW)
    hypothesis = next(
        item for item in summary["hypotheses"]
        if item["cause"] == "conveyance_loss"
    )
    assert hypothesis["state"] == "candidate"
    assert hypothesis["confidence"] <= 55
    assert hypothesis["requires_field_verification"] is True
    assert summary["water_balance"]["root_cause_claim"] is None


def test_derived_fields_cannot_be_self_declared(tmp_path):
    service = WaterIncidentService(tmp_path)
    payload = observation("lagoon_stage", 2.1, unit="ft")
    payload["current_condition_eligible"] = True
    with pytest.raises(ValueError, match="derived_current_condition_fields_forbidden"):
        ingest(service, payload)


def test_laguna_intake_is_append_only_and_idempotent(tmp_path):
    service = WaterIncidentService(tmp_path)
    payload = observation("lagoon_stage", 2.1, unit="ft")
    first = ingest(service, payload, "LC-KEY")
    second = ingest(service, payload, "LC-KEY")
    assert first["receipt_id"] == second["receipt_id"]
    assert second["replayed"] is True
    assert len(service.store.read("laguna_cartagena_observations")) == 1
    changed = dict(payload)
    changed["value"] = 2.2
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        ingest(service, changed, "LC-KEY")


def test_versioned_schemas_validate_observation_and_summary(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    coverage_schema = __import__("json").loads(
        (repo / "schemas/laguna-cartagena/v0.2/laguna_cartagena_coverage.schema.json")
        .read_text(encoding="utf-8")
    )
    coverage_ledger = __import__("json").loads(
        (repo / "config/laguna_cartagena_monitoring_coverage.v0.2.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.validators.validator_for(coverage_schema).check_schema(coverage_schema)
    __import__("jsonschema").validate(coverage_ledger, coverage_schema)

    observation_schema = __import__("json").loads(
        (repo / "schemas/laguna-cartagena/v0.2/laguna_cartagena_observation.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.validators.validator_for(observation_schema).check_schema(observation_schema)

    payload = observation("lagoon_stage", 2.1, unit="ft")
    __import__("jsonschema").validate(
        payload,
        observation_schema,
        format_checker=jsonschema.FormatChecker(),
    )
    service = WaterIncidentService(tmp_path)
    ingest(service, payload)
    summary = service.laguna_cartagena_summary(now=NOW)
    __import__("jsonschema").validate(
        summary,
        __import__("json").loads(
            (repo / "schemas/laguna-cartagena/v0.2/laguna_cartagena_control_plane.schema.json")
            .read_text(encoding="utf-8")
        ),
        format_checker=jsonschema.FormatChecker(),
    )
