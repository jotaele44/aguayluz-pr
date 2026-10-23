"""Read-only real GloTEC capture; grid samples are regional discovery context."""

from __future__ import annotations

import hashlib
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ARCHIVE = (
    Path(__file__).resolve().parents[2] / "data-sources/ionosphere/glotec_20261023T163500Z.zip"
)
ARCHIVE_SHA256 = "b089a7d7e540f2809dab6d6fb0901226f961980e3fe055e020fcdbc745ad64e8"
SOURCE_SHA256 = "511f8418b3a5b8f1a5058ca6045970ad9b5dd62647eb6202a2f5cd5d6ce0393b"
EXPECTED_NODES = {
    (float(-177.5 + x * 5), float(-88.75 + y * 2.5)) for x in range(72) for y in range(72)
}


def snapshot_context(path: Path = ARCHIVE, now: datetime | None = None) -> dict:
    """Validate archive/raw hashes and the full grid before displaying any samples.

    The 10 by 6 degree discovery window is a UI context selection, not a Puerto
    Rico geometry, municipality binding, or proof that grid centers lie on land.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("aware clock required")
    raw_archive = path.read_bytes()
    if hashlib.sha256(raw_archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("archive digest mismatch")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len({info.filename for info in infos}) != len(infos):
            raise ValueError("duplicate archive paths")
        if sum(info.file_size for info in infos) > 10_000_000:
            raise ValueError("archive exceeds snapshot limit")
        receipt_raw = archive.read("receipt.json")
        receipt = json.loads(receipt_raw)
        if receipt.get("state") != "ACQUIRED_UNVERIFIED":
            raise ValueError("source acquisition did not pass")
        attempts = receipt["attempts"]
        if len(attempts) != 2 or attempts[-1]["sha256"] != SOURCE_SHA256:
            raise ValueError("unexpected acquisition lineage")
        for item in attempts:
            content = archive.read(item["sha256"] + ".bin")
            if item["status"] != 200 or len(content) != item["size_bytes"]:
                raise ValueError("source response mismatch")
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("source digest mismatch")
        value = json.loads(content)
    if (
        value.get("type") != "FeatureCollection"
        or value.get("product") != "GloTEC Total Electron Content"
    ):
        raise ValueError("unexpected product")
    if value.get("metadata", {}).get("variables", {}).get("tec", {}).get("units") != "TECU":
        raise ValueError("unknown TEC units")
    if value.get("cadence") != 10:
        raise ValueError("cadence changed; review schema")
    observed = datetime.fromisoformat(value["time_tag"].replace("Z", "+00:00"))
    retrieved = datetime.fromisoformat(receipt["retrieved_utc"])
    if (
        observed.tzinfo is None
        or retrieved.tzinfo is None
        or observed > retrieved
        or retrieved > now
    ):
        raise ValueError("invalid snapshot timing")
    features = value.get("features")
    if not isinstance(features, list):
        raise ValueError("missing features")
    nodes = set()
    selected = []
    missing = 0
    for feature in features:
        if feature.get("type") != "Feature" or feature.get("geometry", {}).get("type") != "Point":
            raise ValueError("non-point feature")
        coords = feature["geometry"].get("coordinates")
        if not isinstance(coords, list) or len(coords) != 2:
            raise ValueError("coordinate dimension changed")
        if any(type(n) not in {int, float} or not math.isfinite(n) for n in coords):
            raise ValueError("invalid coordinates")
        node = tuple(coords)
        if node in nodes:
            raise ValueError("duplicate grid node")
        nodes.add(node)
        p = feature.get("properties")
        if not isinstance(p, dict) or set(p) != {"tec", "anomaly", "hmF2", "NmF2", "quality_flag"}:
            raise ValueError("property schema changed")
        flag = p["quality_flag"]
        if type(flag) is not int or not 0 <= flag <= 5:
            raise ValueError("unknown quality flag")
        tec = p["tec"]
        if tec is None:
            missing += 1
        elif type(tec) not in {int, float} or not math.isfinite(tec) or not 0 <= tec <= 300:
            raise ValueError("invalid TEC")
        lon, lat = coords
        if -70 <= lon <= -60 and 16 <= lat <= 22:
            selected.append(
                {
                    "source_feature_index": len(nodes) - 1,
                    "longitude": lon,
                    "latitude": lat,
                    "raw_feature": feature,
                }
            )
    if nodes != EXPECTED_NODES or len(features) != len(EXPECTED_NODES):
        raise ValueError("grid positions incomplete or unexpected")
    return {
        "state": "ARCHIVED_SNAPSHOT",
        "kind": "MODEL",
        "metric": "TEC",
        "units": "TECU",
        "observed_at": value["time_tag"],
        "retrieved_at": receipt["retrieved_utc"],
        "freshness": "STALE" if (now - observed).total_seconds() > 1800 else "FRESH",
        "source_url": attempts[-1]["url"],
        "source_sha256": SOURCE_SHA256,
        "archive_sha256": ARCHIVE_SHA256,
        "total_features": len(features),
        "missing_tec": missing,
        "selected_count": len(selected),
        "excluded_count": len(features) - len(selected),
        "selection": {"bbox": [-70, 16, -60, 22], "role": "DISCOVERY_CONTEXT_ONLY"},
        "spatial_binding": "CANDIDATE_NOT_IDENTITY",
        "grid_resolution_degrees": [2.5, 5],
        "rows": selected,
        "impact": "UNKNOWN",
        "operational_use_allowed": False,
    }
