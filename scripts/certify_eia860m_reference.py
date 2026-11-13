#!/usr/bin/env python3
"""Acquire and certify the January/February 2026 EIA-860M reference snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from aguayluz.source_intelligence.adapters.base import RawArtifact
from aguayluz.source_intelligence.adapters.eia860m import (
    EIA860MAdapter,
    compare_identity_snapshots,
)
from aguayluz.source_intelligence.health import evaluate_health
from aguayluz.source_intelligence.runtime import (
    freeze_health_receipt,
    persist_source_manifestation,
    verify_source_manifestation,
)

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SNAPSHOTS = {
    "2026-01": {
        "url": "https://www.eia.gov/electricity/data/eia860m/archive/xls/january_generator2026.xlsx",
        "sha256": "a02a0262c98e6b4fc8451e3f88c3983c2edd015b1bff2c5174df91e331ae9cf8",
    },
    "2026-02": {
        "url": "https://www.eia.gov/electricity/data/eia860m/archive/xls/february_generator2026.xlsx",
        "sha256": "9f76e3a186ba0814ea836a357213bab0ea8e18955d862a92e877dc028af755e8",
    },
}


def _fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AguaYLuz-SourceIntelligence/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        final_url = response.geturl()
        parsed = urlparse(final_url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.eia.gov", "eia.gov"}:
            raise ValueError(f"unexpected redirect target: {final_url}")
        payload = response.read(100 * 1024 * 1024 + 1)
        if not payload or len(payload) > 100 * 1024 * 1024:
            raise ValueError("EIA source payload empty or oversized")
        media_type = response.headers.get_content_type()
    return payload, media_type


def _normalized(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(row["normalized"]) for row in rows]


def _status_counts(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["normalized"]["status_code"])
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _nameplate_total(rows: list[dict[str, object]]) -> float:
    return round(
        sum(float(row["normalized"]["nameplate_mw"]) for row in rows),
        6,
    )


def acquire_snapshot(
    period: str,
    output: Path,
    adapter: EIA860MAdapter,
) -> dict[str, object]:
    specification = SNAPSHOTS[period]
    url = specification["url"]
    payload, media_type = _fetch(url)
    digest = hashlib.sha256(payload).hexdigest()
    expected = specification["sha256"]
    if digest != expected:
        raise ValueError(
            f"{period} BYTE contradiction: expected {expected}, acquired {digest}"
        )

    retrieved_at = datetime.now(timezone.utc)
    artifact = RawArtifact(
        source_family_id="EIA_860M",
        locator=url,
        content=payload,
        media_type=media_type or MEDIA_TYPE,
        retrieved_at_iso=retrieved_at.isoformat().replace("+00:00", "Z"),
    )
    adapter.validate_transport(artifact)
    schema_fingerprint = adapter.fingerprint_schema(artifact)
    operating = adapter.parse_operating_pr_hydro(artifact)
    retired = adapter.parse_retired_pr_hydro(artifact)

    if len(operating) != 20:
        raise ValueError(f"{period} expected 20 Operating_PR hydro rows, got {len(operating)}")
    if _nameplate_total(operating) != 98.1:
        raise ValueError(
            f"{period} expected 98.1 MW Operating_PR nameplate, "
            f"got {_nameplate_total(operating)}"
        )
    status_counts = _status_counts(operating)
    if status_counts != {"OP": 19, "SB": 1}:
        raise ValueError(
            f"{period} expected Operating_PR statuses OP=19/SB=1, got {status_counts}"
        )

    manifestation = persist_source_manifestation(
        output,
        artifact,
        schema_fingerprint=schema_fingerprint,
        record_count=len(operating) + len(retired),
        state="PARSED_REFERENCE_PASS",
    )
    verify_source_manifestation(output, manifestation)

    health = evaluate_health(
        "EIA_860M",
        now=retrieved_at,
        last_check=retrieved_at,
        last_success=retrieved_at,
        current_sha256=digest,
        schema_fingerprint=schema_fingerprint,
        record_count=len(operating),
        expected_nonzero=True,
        changed=True,
    )
    health_sha256, health_path = freeze_health_receipt(
        output,
        health,
        checked_at=retrieved_at,
    )
    source_copy = output / "named_sources" / f"{period}.xlsx"
    source_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        output / "objects" / "sha256" / digest[:2] / digest,
        source_copy,
    )

    return {
        "period": period,
        "source_url": url,
        "byte_sha256": digest,
        "byte_count": len(payload),
        "media_type": media_type,
        "schema_fingerprint": schema_fingerprint,
        "manifestation_id": manifestation.manifestation_id,
        "health_receipt_sha256": health_sha256,
        "health_receipt_path": health_path.relative_to(output).as_posix(),
        "operating_count": len(operating),
        "retired_count": len(retired),
        "operating_nameplate_mw": _nameplate_total(operating),
        "operating_status_counts": status_counts,
        "operating_rows": _normalized(operating),
        "retired_rows": _normalized(retired),
    }


def run(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    adapter = EIA860MAdapter()
    january = acquire_snapshot("2026-01", output, adapter)
    february = acquire_snapshot("2026-02", output, adapter)
    replay = compare_identity_snapshots(
        january["operating_rows"],
        february["operating_rows"],
    )
    expected_replay = {
        "intersection": 20,
        "a_only": 0,
        "b_only": 0,
        "union": 20,
        "symmetric_difference": 0,
        "changed": 0,
        "changed_keys": [],
        "a_nameplate_mw": 98.1,
        "b_nameplate_mw": 98.1,
    }
    if replay != expected_replay:
        raise ValueError(f"Jan-Feb replay contradiction: {replay}")

    summary = {
        "schema_version": "aguayluz.eia860m-reference-certification/v1",
        "state": "PASS",
        "retrieval_environment": "github_actions_or_equivalent_networked_runner",
        "snapshots": {"2026-01": january, "2026-02": february},
        "jan_feb_replay": replay,
        "invariants": {
            "raw_bytes_acquired": True,
            "expected_sha256_verified": True,
            "xlsx_schema_pass": True,
            "operating_pr_parser_pass": True,
            "retired_pr_parser_pass": True,
            "plant_generator_identity_pass": True,
            "immutable_manifestation_receipts_pass": True,
            "runtime_health_receipts_pass": True,
        },
    }
    encoded = (
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    summary_path = output / "certification.json"
    summary_path.write_bytes(encoded)
    (output / "certification.sha256").write_text(
        hashlib.sha256(encoded).hexdigest() + "  certification.json\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/eia860m-reference"),
    )
    args = parser.parse_args()
    summary = run(args.output)
    print(json.dumps(summary["invariants"], sort_keys=True))
    print(f"reference certification: {summary['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
