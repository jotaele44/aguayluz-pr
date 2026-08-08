"""Bounded provider acquisition, shadow ingestion, and receipt materialization."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from server.backend.water_disruption import WaterIncidentService

from .http_client import (
    neon_data_url,
    neon_site_url,
    request_url,
    usgs_iv_url,
    usgs_ogc_url,
    wqx3_url,
)
from .model import (
    ALL_USGS_SITE_IDS,
    DIRECT_SITE_IDS,
    NEON_PRODUCTS,
    NEON_SITE,
    FetchReceipt,
    canonical_json,
    deduplicate_observations,
    sha256_bytes,
    utcnow,
)
from .neon import extract_neon_availability
from .replay import run_replay_matrix, validate_replay_matrix
from .usgs import parse_usgs_iv, parse_usgs_ogc, parse_wqx3_csv


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _assert_secret_absent(output_dir: Path, token: str | None) -> None:
    if not token:
        return
    encoded = token.encode("utf-8")
    for path in output_dir.rglob("*"):
        if path.is_file() and encoded in path.read_bytes():
            raise RuntimeError(f"secret_materialized:{path.relative_to(output_dir)}")


def _provider_gaps() -> list[dict[str, str]]:
    return [
        {
            "provider": "USFWS",
            "status": "no_machine_readable_current_hydrologic_endpoint_identified",
            "promotion": "forbidden",
        },
        {
            "provider": "DRNA",
            "status": "no_machine_readable_current_lagoon_field_series_identified",
            "promotion": "forbidden",
        },
        {
            "provider": "AAA",
            "status": "no_synchronized_treatment_withdrawal_gate_or_leak_feed_identified",
            "promotion": "forbidden",
        },
        {
            "provider": "Southwest irrigation operator",
            "status": "no_synchronized_turnout_gate_leak_or_terminal_flow_feed_identified",
            "promotion": "forbidden",
        },
        {
            "provider": "field campaign",
            "status": "not_executed_no_supplied_field_records_or_instrument_access",
            "promotion": "forbidden",
        },
    ]


def run_probe(output_dir: Path, now: datetime | None = None) -> dict[str, Any]:
    now = (now or utcnow()).astimezone(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    receipts: list[FetchReceipt] = []
    candidates: list[dict[str, Any]] = []

    receipt, body = request_url(
        source_id="USGS_NWIS_IV_EXACT_SITES",
        provider="USGS",
        url=usgs_iv_url(ALL_USGS_SITE_IDS),
        output_dir=output_dir,
    )
    receipts.append(receipt)
    candidates.extend(parse_usgs_iv(body, receipt))

    for site_id in ALL_USGS_SITE_IDS:
        for collection in (
            "latest-continuous",
            "latest-field-measurements",
            "time-series-metadata",
        ):
            receipt, body = request_url(
                source_id=f"USGS_OGC_{collection}_{site_id}",
                provider="USGS",
                url=usgs_ogc_url(collection, site_id),
                output_dir=output_dir,
            )
            receipts.append(receipt)
            if collection in {"latest-continuous", "latest-field-measurements"}:
                candidates.extend(parse_usgs_ogc(body, receipt))

    for site_id in DIRECT_SITE_IDS:
        receipt, body = request_url(
            source_id=f"WQP_WQX3_{site_id}",
            provider="USGS/WQP",
            url=wqx3_url(site_id, now),
            output_dir=output_dir,
        )
        receipts.append(receipt)
        candidates.extend(parse_wqx3_csv(body, receipt, site_id))

    neon_token = os.environ.get("NEON_API_TOKEN") or os.environ.get("NEON_API_KEY")
    neon_headers = {"X-API-Token": neon_token} if neon_token else {}
    receipt, body = request_url(
        source_id="NEON_SITE_LAJA",
        provider="NEON",
        url=neon_site_url(),
        output_dir=output_dir,
        extra_headers=neon_headers,
    )
    receipts.append(receipt)
    neon_availability = extract_neon_availability(body)

    months = sorted(
        {now.strftime("%Y-%m"), (now - timedelta(days=31)).strftime("%Y-%m")}
    )
    for product in NEON_PRODUCTS:
        for month in months:
            receipt, _body = request_url(
                source_id=f"NEON_DATA_{product}_{NEON_SITE}_{month}",
                provider="NEON",
                url=neon_data_url(product, month),
                output_dir=output_dir,
                extra_headers=neon_headers,
            )
            receipts.append(receipt)

    candidates = deduplicate_observations(candidates)
    service = WaterIncidentService(output_dir / "shadow_store")
    intake_receipts = [
        service.intake(observation, f"LIVE_PROBE:{observation['observation_id']}")
        for observation in candidates
    ]
    summary = service.laguna_cartagena_summary(now=now)
    replay_matrix = run_replay_matrix(now)
    replay_failures = validate_replay_matrix(replay_matrix)

    current = summary["current_condition"]
    direct_count = int(current["direct_observation_count"])
    eligible_count = int(current["eligible_observation_count"])
    if direct_count > 0 and not current["missing_required_metrics"]:
        outcome = "populated_complete_direct_window"
    elif direct_count > 0:
        outcome = "partial_direct_current_window"
    elif eligible_count > 0:
        outcome = "context_only"
    else:
        outcome = "blocked_no_current_direct_window"

    manifest = [asdict(receipt) for receipt in receipts]
    final_receipt = {
        "schema_version": "aguayluz.laguna-cartagena-live-probe-receipt/v0.3",
        "generated_at": now.isoformat(),
        "outcome": outcome,
        "shadow_mode": True,
        "notifications_enabled": False,
        "automatic_control_actions_enabled": False,
        "production_promotion_enabled": False,
        "raw_response_count": len(manifest),
        "candidate_observation_count": len(candidates),
        "eligible_observation_count": eligible_count,
        "direct_current_observation_count": direct_count,
        "missing_required_metrics": current["missing_required_metrics"],
        "synchronization_status": summary["synchronization"]["status"],
        "water_balance_status": summary["water_balance"]["status"],
        "provider_gaps": _provider_gaps(),
        "neon_availability": neon_availability,
        "replay_failures": replay_failures,
        "preserve": summary["preserve"],
        "source_manifest_sha256": sha256_bytes(canonical_json(manifest).encode()),
        "observation_set_sha256": sha256_bytes(canonical_json(candidates).encode()),
        "summary_sha256": sha256_bytes(canonical_json(summary).encode()),
        "replay_matrix_sha256": sha256_bytes(canonical_json(replay_matrix).encode()),
    }

    _write_json(output_dir / "acquisition_manifest.json", manifest)
    _write_json(output_dir / "candidate_observations.json", candidates)
    _write_json(output_dir / "intake_receipts.json", intake_receipts)
    _write_json(output_dir / "control_plane_summary.json", summary)
    _write_json(output_dir / "replay_matrix.json", replay_matrix)
    _write_json(output_dir / "final_receipt.json", final_receipt)
    _assert_secret_absent(output_dir, neon_token)
    if replay_failures:
        raise RuntimeError("replay_invariant_failure:" + ",".join(replay_failures))
    return final_receipt
