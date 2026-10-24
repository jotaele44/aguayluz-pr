"""Development-only NOAA acquisition experiment; never writes production data.

Freeze response bytes and diagnostic receipts before any interpretation. A captured
FeatureCollection is only acquisition evidence, not geographic certification.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://services.swpc.noaa.gov/products/glotec/geojson_2d_urt/"
NAME = re.compile(r"glotec_icao_\d{8}T\d{6}Z\.geojson")
MAX_BYTES = 8_000_000


def freeze(directory: Path, raw: bytes) -> str:
    """Idempotent content-addressed byte preservation; collisions fail closed."""
    digest = hashlib.sha256(raw).hexdigest()
    path = directory / f"{digest}.bin"
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("snapshot collision")
    else:
        path.write_bytes(raw)
    return digest


def request_bytes(url: str) -> tuple[int, bytes]:
    """Bounded fixed-origin acquisition, including HTTP failure bodies."""
    request = Request(url, headers={"User-Agent": "Aguayluz-Ionosphere-Audit/0.1"})
    try:
        response = urlopen(request, timeout=30)  # noqa: S310 - fixed NOAA origin
    except HTTPError as exc:
        response = exc
    with response:
        if not response.geturl().startswith(BASE):
            raise ValueError("unexpected redirect origin")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("response exceeds acquisition limit")
        return response.code, raw


def inspect_capture(raw: bytes) -> dict:
    """Inventory raw schema without assuming properties or municipality identity."""
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise ValueError("not a FeatureCollection")
    rows = value.get("features")
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty or missing feature list")
    fields = set()
    geometry_types = set()
    null_geometries = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "Feature":
            raise ValueError("malformed feature")
        properties = row.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("missing feature properties")
        fields.update(properties)
        geometry = row.get("geometry")
        if geometry is None:
            null_geometries += 1
        elif isinstance(geometry, dict) and isinstance(geometry.get("type"), str):
            geometry_types.add(geometry["type"])
        else:
            raise ValueError("malformed geometry")
    return {
        "feature_count": len(rows),
        "property_fields": sorted(fields),
        "geometry_types": sorted(geometry_types),
        "null_geometries": null_geometries,
        "top_level_fields": sorted(value),
        "sample_features": rows[:2],
        "geographic_certification": "UNRESOLVED",
    }


def capture(directory: Path, fetch=request_bytes) -> dict:
    """Attempt one listing and latest listed file; keep failure distinct from zero."""
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {
        "state": "BLOCKED",
        "attempts": [],
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "measurement_count": None,
        "geographic_certification": "UNRESOLVED",
    }
    raw = b""
    try:
        for is_listing in (True, False):
            if is_listing:
                url = BASE
            else:
                names = sorted(set(NAME.findall(raw.decode("utf-8"))))
                if not names:
                    raise ValueError("no matching files in frozen listing")
                url = BASE + names[-1]
            status, raw = fetch(url)
            digest = freeze(directory, raw)
            receipt["attempts"].append(
                {"url": url, "status": status, "sha256": digest, "size_bytes": len(raw)}
            )
            if status != 200:
                raise ValueError(f"HTTP {status}")
        receipt["schema_inventory"] = inspect_capture(raw)
        receipt["state"] = "ACQUIRED_UNVERIFIED"
    except (ValueError, OSError, URLError) as exc:
        receipt["error"] = str(exc)
    serialized = (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode()
    digest = freeze(directory, serialized)
    # This pointer is local to an isolated CI job. Immutable receipts retain every attempt.
    (directory / "receipt.json").write_bytes(serialized)
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "receipt_sha256": digest,
                "error": receipt.get("error"),
                "schema": receipt.get("schema_inventory"),
            }
        )
    )
    return receipt


if __name__ == "__main__":
    result = capture(Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/ionosphere-acquisition"))
    raise SystemExit(0 if result["state"] == "ACQUIRED_UNVERIFIED" else 1)
