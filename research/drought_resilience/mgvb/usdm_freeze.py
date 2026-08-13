from __future__ import annotations

import re
import tempfile
import zipfile
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .content_store import ingest
from .manifest import canonical_sha256, write_manifest
from .transport import acquire

WINDOW_START = date(2014, 1, 1)
WINDOW_END = date(2016, 12, 31)
USDM_URLS = {
    2014: "https://droughtmonitor.unl.edu/data/gml/2014_USDM_GML.zip",
    2015: "https://droughtmonitor.unl.edu/data/gml/2015_USDM_GML.zip",
    2016: "https://droughtmonitor.unl.edu/data/gml/2016_USDM_GML.zip",
}
DATE_RE = re.compile(r"(?i)USDM[_-]?(20\d{6})")


def expected_issue_dates() -> list[date]:
    current = WINDOW_START
    output: list[date] = []
    while current <= WINDOW_END:
        if current.weekday() == 1:
            output.append(current)
        current += timedelta(days=1)
    return output


def archive_dates(path: Path) -> set[date]:
    output: set[date] = set()
    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            match = DATE_RE.search(Path(member).name)
            if not match:
                continue
            try:
                output.add(datetime.strptime(match.group(1), "%Y%m%d").date())
            except ValueError:
                continue
    return output


def closure(paths: list[Path]) -> dict[str, Any]:
    observed: set[date] = set()
    for path in paths:
        observed.update(archive_dates(path))
    expected = set(expected_issue_dates())
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if len(observed) != 156 or missing or unexpected:
        raise ValueError(
            "USDM closure failed "
            f"observed={len(observed)} missing={len(missing)} "
            f"unexpected={len(unexpected)}"
        )
    return {
        "expected_week_count": 156,
        "observed_week_count": 156,
        "first_issue": min(observed).isoformat(),
        "last_issue": max(observed).isoformat(),
        "missing": [],
        "unexpected": [],
    }


def freeze(
    evidence_root: Path,
    *,
    offline_input_dir: Path | None = None,
) -> tuple[Path, str]:
    objects: list[dict[str, Any]] = []
    local_archives: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="aguayluz-usdm-mgvb-") as raw:
        raw_root = Path(raw)
        for year, url in sorted(USDM_URLS.items()):
            filename = f"{year}_USDM_GML.zip"
            destination = raw_root / filename
            offline_source = (
                offline_input_dir / filename if offline_input_dir is not None else None
            )
            receipt = acquire(url, destination, offline_source=offline_source)
            stored = ingest(destination, evidence_root)
            local_archives.append(destination)
            objects.append(
                {
                    "source_id": f"USDM_GML_{year}",
                    "year": year,
                    "transport": asdict(receipt),
                    "stored": asdict(stored),
                }
            )

        archive_closure = closure(local_archives)

    manifest = {
        "schema_version": "aguayluz.drought-usdm-freeze/v0.1",
        "source_family": "USDM",
        "research_window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "objects": objects,
        "closure": archive_closure,
        "epistemic_role": "composite_context_not_independent_drought_class",
        "certification": "candidate",
    }
    manifest["content_identity_sha256"] = canonical_sha256(
        {key: value for key, value in manifest.items() if key != "generated_utc"}
    )
    path = evidence_root / "manifests" / "usdm_2014_2016.json"
    manifest_sha = write_manifest(path, manifest)
    return path, manifest_sha
