"""Fail-closed persisted PITIRRE-to-Aguayluz frozen-model package consumer."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = (
    Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "data-sources/ionosphere"
)
PACKAGE_SHA256 = "4bcbc60a48075456b022f085c6972b54e145fe987e46a2b89c0b23eaa60d7e6d"
SCHEMA_SHA256 = "21dc2ed3b3b5598b428f560d62cb6eb93c25478a6c6a3ec5911056932d3faf5c"


def consume_glotec_package(raw: bytes, schema_raw: bytes, snapshot: dict) -> dict:
    """Validate version/role/counts and exact source-row binding, without writes."""
    if hashlib.sha256(raw).hexdigest() != PACKAGE_SHA256:
        raise ValueError("producer package digest mismatch")
    if hashlib.sha256(schema_raw).hexdigest() != SCHEMA_SHA256:
        raise ValueError("producer schema digest mismatch")
    value = json.loads(raw)
    if (
        value.get("schema_version") != "pitirre-glotec-package-v1"
        or value.get("producer_repository_id") != 1261399537
    ):
        raise ValueError("wrong producer identity or package version")
    if (
        value.get("operational_use_allowed") is not False
        or value.get("source_sha256") != snapshot["source_sha256"]
    ):
        raise ValueError("source or use-policy mismatch")
    if value.get("selection") != snapshot["selection"]:
        raise ValueError("selection scope changed")
    records = value.get("records")
    if not isinstance(records, list) or len(records) != snapshot["selected_count"]:
        raise ValueError("record conservation failed")
    if (value.get("source_count"), value.get("retained_count"), value.get("excluded_count")) != (
        snapshot["total_features"],
        len(records),
        snapshot["excluded_count"],
    ):
        raise ValueError("package accounting mismatch")
    validator = Draft202012Validator(json.loads(schema_raw))
    ids = set()
    for row, source in zip(records, snapshot["rows"], strict=True):
        validator.validate(row)
        index = source["source_feature_index"]
        expected_id = f"glotec:{snapshot['source_sha256']}:{index}"
        if row["observation_id"] != expected_id or expected_id in ids:
            raise ValueError("source row identity or duplicate failure")
        ids.add(expected_id)
        if (
            row["adapter"]["legacy_contract"] != "glotec_model"
            or row["payload"].get("kind") != "MODEL"
        ):
            raise ValueError("wrong source role")
        if row["payload"].get("raw_feature") != source["raw_feature"]:
            raise ValueError("whole source row differs")
        if row["payload"].get("source_manifest") != {
            "url": snapshot["source_url"],
            "sha256": snapshot["source_sha256"],
            "row_index": index,
            "observed_at": snapshot["observed_at"],
            "retrieved_at": snapshot["retrieved_at"],
        }:
            raise ValueError("manifestation lineage differs")
        if row["source_ref"] != {
            "source_id": "noaa:glotec",
            "source_type_raw": "GloTEC Total Electron Content",
            "source_record_id": index,
            "lineage_id": snapshot["source_sha256"],
        }:
            raise ValueError("producer source binding differs")
        if row["spatial"] != {
            "mode": "SOURCE_POINT",
            "lat": source["latitude"],
            "lon": source["longitude"],
            "geometry_status_raw": "MODEL_GRID_NODE",
        }:
            raise ValueError("producer coordinate role differs")
        if row["event_time_raw"] != snapshot["observed_at"]:
            raise ValueError("producer epoch differs")
    return {
        "state": "PASS_FROZEN_TRANSPORT",
        "producer_repository_id": 1261399537,
        "package_sha256": PACKAGE_SHA256,
        "schema_sha256": SCHEMA_SHA256,
        "record_count": len(records),
        "records": records,
        "persisted": True,
        "operational_use_allowed": False,
    }


def load_frozen_transport(snapshot: dict) -> dict:
    """Read the exact committed producer export; never fetch mutable inputs."""
    manifest_raw = (ROOT / "pitirre_manifest.json").read_bytes()
    if (
        hashlib.sha256(manifest_raw).hexdigest()
        != "d69186f0f4ce1ab5fcfec065c249c3c72f8c23e0bc6973bd16739aade6b3fba6"
    ):
        raise ValueError("producer source manifest changed")
    manifest = json.loads(manifest_raw)
    result = consume_glotec_package(
        (ROOT / "pitirre_glotec_context.package.json").read_bytes(),
        (ROOT / "pitirre_observation.v2.schema.json").read_bytes(),
        snapshot,
    )
    result["producer_commit"] = manifest["producer_candidate_commit"]
    result["producer_module_git_blob"] = manifest["producer_module_git_blob"]
    return result


def load_reference_coverage() -> dict:
    """Expose the exact recomputable topology receipt, tied to the frozen reference."""
    report = (ROOT / "reference_coverage.json").read_bytes()
    if (
        hashlib.sha256(report).hexdigest()
        != "1bd3d79f1cbe16471d1548a1bcc18df4a24e32667634c35e8b2cf6c653d3656f"
    ):
        raise ValueError("reference coverage receipt changed")
    value = json.loads(report)
    reference = (ROOT.parents[1] / "data/geo/pr_municipios.geojson").read_bytes()
    if hashlib.sha256(reference).hexdigest() != value["reference_sha256"]:
        raise ValueError("reference geometry changed since audit")
    if value["classified_count"] + value["excluded_count"] != value["reference_count"]:
        raise ValueError("reference accounting mismatch")
    return value
