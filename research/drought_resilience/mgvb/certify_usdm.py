from __future__ import annotations

from pathlib import Path
from typing import Any

from .content_store import StoredObject, verify
from .manifest import read_manifest

EXPECTED_SUPPLEMENTAL_DATES = [
    "2015-10-06",
    "2015-10-13",
    "2015-10-20",
    "2015-10-27",
    "2015-11-03",
    "2015-11-10",
    "2015-11-17",
    "2015-11-24",
    "2015-12-01",
    "2015-12-08",
    "2015-12-15",
    "2015-12-22",
    "2015-12-29",
]


def certify(path: Path) -> dict[str, Any]:
    manifest = read_manifest(path)
    if manifest.get("schema_version") != "aguayluz.drought-usdm-freeze/v0.2":
        raise ValueError("unsupported manifest schema")
    if manifest.get("source_family") != "USDM":
        raise ValueError("wrong source family")
    if manifest.get("epistemic_role") != "composite_context_not_independent_drought_class":
        raise ValueError("USDM epistemic-role invariant violated")

    objects = manifest.get("objects")
    if not isinstance(objects, list) or len(objects) != 16:
        raise ValueError("expected 3 annual + 13 supplemental USDM objects")

    annual = [item for item in objects if item.get("object_kind") == "annual_archive"]
    supplemental = [
        item for item in objects if item.get("object_kind") == "supplemental_weekly"
    ]
    annual_years = [item.get("issue_or_year") for item in annual]
    if annual_years != [2014, 2015, 2016]:
        raise ValueError(f"unexpected USDM annual object sequence: {annual_years}")
    supplemental_dates = [str(item.get("issue_or_year")) for item in supplemental]
    if supplemental_dates != EXPECTED_SUPPLEMENTAL_DATES:
        raise ValueError(f"unexpected supplemental USDM sequence: {supplemental_dates}")

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
        "expected_week_count": 155,
        "observed_week_count": 155,
        "first_issue": "2014-01-07",
        "last_issue": "2016-12-27",
        "known_non_issue_dates": ["2016-11-01"],
        "missing": [],
        "unexpected": [],
    }
    if closure != expected:
        raise ValueError(f"USDM closure mismatch: {closure}")

    if manifest.get("annual_object_count") != 3:
        raise ValueError("annual object count mismatch")
    if manifest.get("supplemental_weekly_object_count") != 13:
        raise ValueError("supplemental weekly object count mismatch")

    return {
        "source_family": "USDM",
        "annual_objects": 3,
        "supplemental_weekly_objects": 13,
        "week_count": 155,
        "known_non_issue_dates": ["2016-11-01"],
        "missing": 0,
        "unexpected": 0,
        "status": "certified",
    }
