from __future__ import annotations

from pathlib import Path
from typing import Any

from .content_store import StoredObject, verify
from .manifest import read_manifest


def certify(path: Path) -> dict[str, Any]:
    manifest = read_manifest(path)
    if manifest.get("schema_version") != "aguayluz.drought-usdm-freeze/v0.1":
        raise ValueError("unsupported manifest schema")
    if manifest.get("source_family") != "USDM":
        raise ValueError("wrong source family")
    if manifest.get("epistemic_role") != "composite_context_not_independent_drought_class":
        raise ValueError("USDM epistemic-role invariant violated")

    objects = manifest.get("objects")
    if not isinstance(objects, list) or len(objects) != 3:
        raise ValueError("expected exactly three annual USDM objects")
    years = [item.get("year") for item in objects]
    if years != [2014, 2015, 2016]:
        raise ValueError(f"unexpected USDM annual object sequence: {years}")

    for item in objects:
        stored = item.get("stored")
        if not isinstance(stored, dict):
            raise ValueError("stored-object metadata missing")
        verify(
            StoredObject(
                sha256=str(stored["sha256"]),
                bytes=int(stored["bytes"]),
                object_path=str(stored["object_path"]),
            )
        )

    closure = manifest.get("closure")
    expected = {
        "expected_week_count": 156,
        "observed_week_count": 156,
        "first_issue": "2014-01-07",
        "last_issue": "2016-12-27",
        "missing": [],
        "unexpected": [],
    }
    if closure != expected:
        raise ValueError(f"USDM closure mismatch: {closure}")

    return {
        "source_family": "USDM",
        "annual_objects": 3,
        "week_count": 156,
        "missing": 0,
        "unexpected": 0,
        "status": "certified",
    }
