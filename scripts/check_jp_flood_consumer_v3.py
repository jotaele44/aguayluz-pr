#!/usr/bin/env python3
"""AguayLuz-side JP_FLOOD_CERTIFICATION_V3 contract gate."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ingest_jp_flood_documents.py"
_spec = importlib.util.spec_from_file_location("jp_flood_consumer", MODULE_PATH)
consumer = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(consumer)

EXPECTED_CERT_SHA = "e6832834f875900dda4c3f5f3b25444e39e9f804d1279ffb45ddecee9082c60c"
EXPECTED_PRODUCER_SHA = "f665aba3176f9defbdce322b1e480c8db596df666ea130ccb435bf46a66a2e78"
EXPECTED_SOURCE_STATES = {
    "AVAILABLE": "Available",
    "LISTED_BUT_MISSING": "Listed · source file missing",
    "NOT_LISTED": "Not listed in source series",
}
EXPECTED_BADGE = "Byte certified 78/78"


class GateError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root: Path = ROOT) -> dict:
    producer_path = root / "data/jp_flood_documents_producer_contract.json"
    certification_path = root / "data/jp_flood_documents_byte_certification.json"

    if sha256(producer_path) != EXPECTED_PRODUCER_SHA:
        raise GateError("CROSS_REPO_CONTRACT_DRIFT_GATE producer contract bytes drifted")
    if sha256(certification_path) != EXPECTED_CERT_SHA:
        raise GateError("CROSS_REPO_CONTRACT_DRIFT_GATE byte certification bytes drifted")

    producer = consumer.validate_producer_contract(producer_path)
    certification = consumer.validate_byte_certification(certification_path)

    if producer["source_contract"]["manifest_version"] != "2.1":
        raise GateError("CROSS_REPO_CONTRACT_DRIFT_GATE producer manifest version drifted")
    if certification["counts"]["municipality_denominator"] != 78:
        raise GateError("CROSS_REPO_CONTRACT_DRIFT_GATE municipality denominator drifted")
    if certification["counts"]["byte_verified_count"] != 78:
        raise GateError("CROSS_REPO_CONTRACT_DRIFT_GATE byte denominator drifted")
    if certification["counts"]["failure_count"] != 0:
        raise GateError("CROSS_REPO_CONTRACT_DRIFT_GATE certification failures are nonzero")

    page = (root / "dashboard/src/pages/MunicipioDetailPage.jsx").read_text(encoding="utf-8")
    for state, label in EXPECTED_SOURCE_STATES.items():
        if label not in page:
            raise GateError(f"SOURCE_STATE_UI_SEMANTICS_GATE missing label for {state}: {label}")
    if "Byte certified" not in page:
        raise GateError("SOURCE_STATE_UI_SEMANTICS_GATE byte certification badge missing")
    if "flood.byte_certification?.certification_state === 'PASS'" not in page:
        raise GateError("SOURCE_STATE_UI_SEMANTICS_GATE badge is not conditioned on PASS")

    return {
        "schema_version": "aguayluz.jp-flood-consumer-v3/1.0",
        "gates": {
            "CROSS_REPO_CONTRACT_DRIFT_GATE": "PASS",
            "SOURCE_STATE_UI_SEMANTICS_GATE": "PASS",
        },
        "producer_contract_sha256": EXPECTED_PRODUCER_SHA,
        "byte_certification_sha256": EXPECTED_CERT_SHA,
        "counts": certification["counts"],
        "ui_labels": EXPECTED_SOURCE_STATES,
        "ui_badge": EXPECTED_BADGE,
        "invariant": "byte certification PASS never promotes source_state",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report")
    args = parser.parse_args()
    try:
        result = run(ROOT)
    except (GateError, ValueError) as exc:
        print(f"JP_FLOOD_CONSUMER_V3 = FAIL: {exc}")
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    print("JP_FLOOD_CONSUMER_V3 = PASS")
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
