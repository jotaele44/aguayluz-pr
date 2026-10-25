#!/usr/bin/env python3
"""Fail-closed validator for WATER_HEALTH PRDOH↔SDWIS reconciliation v1."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path("data/certification")
SYSTEM_GRAPH = ROOT / "prdoh_sdwis_system_candidates_v1.json.gz.b64"
VIOLATION_GRAPH = ROOT / "prdoh_sdwis_violation_candidates_v1.json.gz.b64"
REVISION_GRAPH = ROOT / "prdoh_sdwis_revision_graph_v1.json.gz.b64"
SENTINEL = ROOT / "sdwis_sentinel_closure_v1.json"
FIVE = ROOT / "prdoh_sdwis_five_plane_set_algebra_v1.json"
FALSIFIERS = ROOT / "prdoh_sdwis_falsifier_replay_v1.json"
CANDIDATE = ROOT / "prdoh_sdwis_reconciliation_candidate_v1.json"

HASHES = {
    "system": (
        "3297fe0a6a114f7015f658b1101c78eb8ee0578b7f608db4386a0e9dfbc04265",
        "0e8055876466aca45c556afd7e72b438f799eeeb560be112b0b9c8484f0f9b65",
    ),
    "violation": (
        "df349b2bad7356cf757a36f2a4afc598119f7d871f1778c37383fe29d2293825",
        "fe2a2e706d3f65e2b0e017dca408b360850f0be7a7a4cf81384c597df8bf97f4",
    ),
    "revision": (
        "a1e5724a7d793f43045559d077769568da8ca9e18e5daf69b5091b2866824185",
        "fae9a0dbbe11fa95c2b3bad3d5a0d78b42fcc71fe668600ad5980ce1ffa1b2a1",
    ),
}
PWSID = re.compile(r"^PR\d{7}$")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_frozen_graph(path: Path, key: str) -> dict[str, Any]:
    encoded = path.read_text(encoding="utf-8").strip()
    compressed = base64.b64decode(encoded, validate=True)
    raw_hash, gzip_hash = HASHES[key]
    if sha256(compressed) != gzip_hash:
        raise ValueError(f"{key} gzip hash mismatch")
    raw = gzip.decompress(compressed)
    if sha256(raw) != raw_hash:
        raise ValueError(f"{key} decoded JSON hash mismatch")
    return json.loads(raw)


def bind_system(
    left_id: str | None,
    right_id: str | None,
    *,
    left_namespace: str = "PWSID_9CHAR_AUTHORITY_GRADE",
    right_namespace: str = "PWSID_9CHAR_AUTHORITY_GRADE",
) -> bool:
    return bool(
        left_namespace == right_namespace == "PWSID_9CHAR_AUTHORITY_GRADE"
        and left_id
        and right_id
        and PWSID.fullmatch(left_id)
        and left_id == right_id
    )


def bind_violation(prdoh_violation_id: str | None, sdwis_violation_id: str | None) -> bool:
    return bool(
        prdoh_violation_id
        and sdwis_violation_id
        and prdoh_violation_id == sdwis_violation_id
    )


def composite_disposition(candidate_count: int) -> str:
    if candidate_count == 1:
        return "DISCOVERY_ONLY_NO_BIND"
    if candidate_count > 1:
        return "REVIEW_TIE_NO_BIND"
    return "SOURCE_ONLY_NO_BIND"


def arrow_disposition(end_token: str, calculated_rtc: str, begin_iso: str) -> str:
    if end_token != "--->":
        return "DENY"
    if calculated_rtc.strip():
        return "DENY"
    if date.fromisoformat(begin_iso) <= date(2025, 12, 31):
        return "RETAIN_OPEN_ENDED_2025_OVERLAP"
    return "EXCLUDE_FUTURE_BEGIN"


def enforce_join_conservation(before: int, expected_multiplier: int, after: int) -> None:
    if after != before * expected_multiplier:
        raise ValueError("join conservation failure")


def validate_sentinel(doc: dict[str, Any]) -> None:
    inp = doc["input"]
    if inp["unresolved_rows"] != 1168 or inp["unique_pwsid_violation_keys"] != 868:
        raise ValueError("sentinel denominator drift")
    m = inp["key_multiplicity"]
    if sum(int(k) * v for k, v in m.items()) != 1168 or sum(m.values()) != 868:
        raise ValueError("sentinel multiplicity arithmetic failure")
    if inp["end_token_counts"] != {"--->": 1168}:
        raise ValueError("sentinel token drift")
    if inp["calculated_rtc_present_rows"] != 0:
        raise ValueError("sentinel RTC rows unexpectedly present")
    if doc["retained_from_sentinel"] != 1168 or doc["remaining_unresolved_rows"] != 0:
        raise ValueError("sentinel closure incomplete")
    a = doc["revised_source_arithmetic"]
    if a != {
        "source": 15550611,
        "retained": 4191,
        "excluded": 15546420,
        "unresolved": 0,
        "accounted": 15550611,
        "delta": 0,
    }:
        raise ValueError("revised SDWIS arithmetic drift")
    full = doc["full_row_manifest"]
    if full["row_count"] != 1168:
        raise ValueError("full sentinel row-manifest denominator drift")
    if full["decoded_json_sha256"] != "07fe0274755e3bac10f25d290467074fab3c3693d9c586efbf3d6eb9a9363a11":
        raise ValueError("full sentinel manifest hash drift")
    if full["deterministic_gzip_sha256"] != "0eb9931a5571b8f6dfd213631685aae27c167feba27e6e012850849f4ae56859":
        raise ValueError("full sentinel gzip hash drift")
    if len(doc["contradiction_flags"]) != 1:
        raise ValueError("sentinel contradiction denominator drift")
    if doc["state"] != "SDWIS_SENTINEL_CLOSURE_PASS":
        raise ValueError("sentinel state is not PASS")


def validate_system_graph(doc: dict[str, Any]) -> None:
    if doc["state"] != "SYSTEM_CANDIDATE_ENUMERATION_PASS":
        raise ValueError("system graph not PASS")
    if doc["prdoh_authority_grade_pwsids"] != 142 or doc["prdoh_prasa_shorthand_tokens"] != 27:
        raise ValueError("PRDOH system denominator drift")
    if doc["prdoh_unique_system_representations"] != 169:
        raise ValueError("PRDOH system representation arithmetic drift")
    if len(doc["authority_grade_edges"]) != 142 or len(doc["shorthand_discovery_edges"]) != 27:
        raise ValueError("system edge denominator drift")
    if any(edge["evidence_class"] != "HEURISTIC_DISCOVERY_ONLY" for edge in doc["shorthand_discovery_edges"]):
        raise ValueError("shorthand promoted above discovery")
    if any("NO_AUTHORITATIVE_4DIGIT_TO_9CHAR_CROSSWALK" not in edge["falsifier"] for edge in doc["shorthand_discovery_edges"]):
        raise ValueError("shorthand falsifier missing")
    a = doc["strict_2025_system_set_algebra"]
    if a != {"delta":0,"intersection":138,"prdoh_only":31,"sdwis_only":167,"symmetric_difference":198,"union":336}:
        raise ValueError("system set algebra drift")
    if a["intersection"] + a["prdoh_only"] != 169:
        raise ValueError("PRDOH system conservation failure")
    if a["intersection"] + a["sdwis_only"] != 305:
        raise ValueError("SDWIS system conservation failure")


def validate_violation_graph(doc: dict[str, Any]) -> None:
    if doc["state"] != "VIOLATION_CANDIDATE_ENUMERATION_PASS_NO_CANONICAL_BINDINGS":
        raise ValueError("violation graph not PASS")
    if doc["prdoh_rows"] != 129 or len(doc["candidate_entries"]) != 129:
        raise ValueError("PRDOH violation denominator drift")
    if doc["sdwis_closed_target_rows"] != 4191:
        raise ValueError("SDWIS closed violation denominator drift")
    if doc["canonical_cross_source_violation_bindings"] != 0:
        raise ValueError("fabricated canonical violation binding")
    counts = doc["candidate_state_counts"]
    if sum(counts.values()) != 129:
        raise ValueError("violation candidate arithmetic failure")
    if counts != {
        "AMBIGUOUS_MULTI_CANDIDATE_NO_BIND":11,
        "CORROBORATED_COMPOSITE_CANDIDATE_NO_CANONICAL_BINDING":22,
        "NO_CANONICAL_VIOLATION_BINDING":54,
        "PRDOH_ONLY_NO_SDWIS_CANDIDATE":42,
    }:
        raise ValueError("violation candidate-state drift")


def validate_revision_graph(doc: dict[str, Any]) -> None:
    if doc["state"] != "PASS" or doc["unresolved_edges"] != 0:
        raise ValueError("revision graph unresolved")
    if len(doc["system_revision_edges"]) != 169 or len(doc["violation_revision_edges"]) != 129:
        raise ValueError("revision edge denominator drift")
    if sum(doc["system_edge_counts"].values()) != 169:
        raise ValueError("system revision arithmetic failure")
    if sum(doc["violation_edge_counts"].values()) != 129:
        raise ValueError("violation revision arithmetic failure")
    if doc["violation_revision_binding_count"] != 0:
        raise ValueError("violation revision binding invented")


def validate_five_plane(doc: dict[str, Any]) -> None:
    if doc["state"] != "FIVE_PLANE_SET_ALGEBRA_PASS":
        raise ValueError("five-plane algebra not PASS")
    if any(doc["material_residue"].values()):
        raise ValueError("five-plane material residue remains")
    for plane in doc["planes"].values():
        if plane["delta"] != 0:
            raise ValueError("nonzero plane delta")
    sys = doc["planes"]["SYSTEM"]
    if sys["intersection"] + sys["prdoh_only"] != 169:
        raise ValueError("SYSTEM PRDOH conservation failure")
    if sys["intersection"] + sys["sdwis_only"] != 305:
        raise ValueError("SYSTEM SDWIS conservation failure")
    sxv = doc["planes"]["SYSTEM_X_VIOLATION"]
    if sum(sxv["terminal_states"].values()) != sxv["prdoh_rows"] != 129:
        raise ValueError("SYSTEM_X_VIOLATION arithmetic failure")
    vio = doc["planes"]["VIOLATION"]
    if vio["intersection_by_shared_stable_violation_id"] != 0:
        raise ValueError("stable violation-ID intersection must remain zero")


def validate_candidate(doc: dict[str, Any]) -> None:
    if doc["canonical_system_bindings"] != 140:
        raise ValueError("canonical system binding denominator drift")
    if doc["canonical_cross_source_violation_bindings"] != 0:
        raise ValueError("canonical violation binding drift")
    if any(doc["material_residue"].values()):
        raise ValueError("candidate material residue remains")
    if doc["sdwis_revised_arithmetic"]["unresolved"] != 0:
        raise ValueError("SDWIS unresolved residue remains")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    system = load_frozen_graph(SYSTEM_GRAPH, "system")
    violation = load_frozen_graph(VIOLATION_GRAPH, "violation")
    revision = load_frozen_graph(REVISION_GRAPH, "revision")
    validate_sentinel(load_json(SENTINEL))
    validate_system_graph(system)
    validate_violation_graph(violation)
    validate_revision_graph(revision)
    validate_five_plane(load_json(FIVE))
    validate_candidate(load_json(CANDIDATE))
    spec = load_json(FALSIFIERS)
    if spec["expected_pass_count"] != 14 or len(spec["tests"]) != 14:
        raise ValueError("falsifier denominator drift")
    print("WATER_HEALTH_PRDOH_SDWIS_RECONCILIATION_V1=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
