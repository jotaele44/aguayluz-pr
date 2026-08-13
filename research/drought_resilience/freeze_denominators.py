#!/usr/bin/env python3
"""Freeze authoritative 2014-2016 Puerto Rico drought denominators.

Research-layer acquisition/evidence utility. It downloads source bytes without
interpreting one drought class as another, records SHA-256 and retrieval metadata,
and fails closed when a declared denominator is incomplete.

Large raw objects belong in a content-addressed evidence directory, not in Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WINDOW_START = date(2014, 1, 1)
WINDOW_END = date(2016, 12, 31)
NCEI_STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
NCEI_INVENTORY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-inventory.txt"
NCEI_BY_STATION_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station"
USDM_ANNUAL_URLS = {
    2014: "https://droughtmonitor.unl.edu/data/gml/2014_USDM_GML.zip",
    2015: "https://droughtmonitor.unl.edu/data/gml/2015_USDM_GML.zip",
    2016: "https://droughtmonitor.unl.edu/data/gml/2016_USDM_GML.zip",
}
USGS_OGC_BASE = "https://api.waterdata.usgs.gov/ogcapi/v0"
PR_BBOX = "-67.95,17.7,-65.2,18.7"
USER_AGENT = "aguayluz-pr-drought-denominator-freezer/0.1"
USDM_DATE_RE = re.compile(r"(?i)usdm[_-]?(20\d{6})")


@dataclass(frozen=True)
class FrozenObject:
    source_id: str
    url: str
    path: str
    bytes: int
    sha256: str
    retrieved_utc: str
    status: str = "frozen"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_usdm_issue_dates() -> list[date]:
    current = WINDOW_START
    dates: list[date] = []
    while current <= WINDOW_END:
        if current.weekday() == 1:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def parse_ghcnd_pr_station_ids(text: str) -> set[str]:
    result: set[str] = set()
    for line in text.splitlines():
        if len(line) < 40:
            continue
        station_id = line[0:11].strip()
        state = line[38:40].strip()
        if station_id and state == "PR":
            result.add(station_id)
    return result


def parse_ghcnd_prcp_inventory(
    text: str,
    station_ids: set[str],
    *,
    start_year: int = 2014,
    end_year: int = 2016,
) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        if len(line) < 45:
            continue
        station_id = line[0:11].strip()
        if station_id not in station_ids:
            continue
        element = line[31:35].strip()
        if element != "PRCP":
            continue
        try:
            first_year = int(line[36:40])
            last_year = int(line[41:45])
        except ValueError:
            continue
        if first_year <= end_year and last_year >= start_year:
            result[station_id] = (first_year, last_year)
    return result


def extract_usdm_dates_from_zip(path: Path) -> set[date]:
    dates: set[date] = set()
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            match = USDM_DATE_RE.search(Path(name).name)
            if not match:
                continue
            try:
                dates.add(datetime.strptime(match.group(1), "%Y%m%d").date())
            except ValueError:
                continue
    return dates


def assert_usdm_archive_closure(paths: list[Path]) -> dict[str, Any]:
    observed: set[date] = set()
    for path in paths:
        observed.update(extract_usdm_dates_from_zip(path))
    expected = set(expected_usdm_issue_dates())
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing or unexpected or len(observed) != 156:
        raise ValueError(
            "USDM archive closure failed: "
            f"observed={len(observed)} expected=156 "
            f"missing={[d.isoformat() for d in missing]} "
            f"unexpected={[d.isoformat() for d in unexpected]}"
        )
    return {
        "expected_week_count": 156,
        "observed_week_count": len(observed),
        "first_issue": min(observed).isoformat(),
        "last_issue": max(observed).isoformat(),
        "missing": [],
        "unexpected": [],
    }


def _download(url: str, destination: Path, timeout: int = 120) -> FrozenObject:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    retrieved = datetime.now(timezone.utc).isoformat()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            with destination.open("wb") as target:
                shutil.copyfileobj(response, target, length=1024 * 1024)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        destination.unlink(missing_ok=True)
        raise
    return FrozenObject(
        source_id="",
        url=url,
        path=str(destination),
        bytes=destination.stat().st_size,
        sha256=sha256_file(destination),
        retrieved_utc=retrieved,
    )


def freeze_url(source_id: str, url: str, destination: Path) -> FrozenObject:
    frozen = _download(url, destination)
    return FrozenObject(
        source_id=source_id,
        **{k: v for k, v in asdict(frozen).items() if k != "source_id"},
    )


def build_usgs_request_plan() -> list[dict[str, Any]]:
    interval = "2014-01-01T00:00:00Z/2016-12-31T23:59:59Z"
    return [
        {
            "source_id": "USGS_TIME_SERIES_METADATA_PR_2014_2016",
            "collection": "time-series-metadata",
            "url": f"{USGS_OGC_BASE}/collections/time-series-metadata/items?f=json&bbox={PR_BBOX}&limit=10000",
            "purpose": "enumerate daily/continuous series before observation acquisition",
            "certification": "query_identity_only",
        },
        {
            "source_id": "USGS_DAILY_PR_2014_2016",
            "collection": "daily",
            "url": f"{USGS_OGC_BASE}/collections/daily/items?f=json&bbox={PR_BBOX}&datetime={interval}&limit=10000",
            "purpose": "daily streamflow/reservoir/groundwater candidate observations",
            "certification": "query_identity_only",
        },
        {
            "source_id": "USGS_FIELD_MEASUREMENTS_PR_2014_2016",
            "collection": "field-measurements",
            "url": f"{USGS_OGC_BASE}/collections/field-measurements/items?f=json&bbox={PR_BBOX}&datetime={interval}&limit=10000",
            "purpose": "discrete discharge/gage-height/groundwater observations",
            "certification": "query_identity_only",
        },
    ]


def freeze_ncei(root: Path) -> tuple[list[FrozenObject], dict[str, Any]]:
    catalog_dir = root / "ncei" / "catalog"
    stations_path = catalog_dir / "ghcnd-stations.txt"
    inventory_path = catalog_dir / "ghcnd-inventory.txt"
    frozen = [
        freeze_url("NCEI_GHCND_STATIONS", NCEI_STATIONS_URL, stations_path),
        freeze_url("NCEI_GHCND_INVENTORY", NCEI_INVENTORY_URL, inventory_path),
    ]
    pr_ids = parse_ghcnd_pr_station_ids(
        stations_path.read_text(encoding="ascii", errors="replace")
    )
    inventory = parse_ghcnd_prcp_inventory(
        inventory_path.read_text(encoding="ascii", errors="replace"), pr_ids
    )
    if not pr_ids:
        raise ValueError("NCEI station denominator unexpectedly empty for state=PR")
    if not inventory:
        raise ValueError("NCEI PRCP denominator unexpectedly empty for 2014-2016")
    denominator_path = root / "ncei" / "prcp_station_denominator.json"
    denominator = {
        "research_window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "catalog_station_count_pr": len(pr_ids),
        "prcp_overlap_station_count": len(inventory),
        "stations": [
            {"station_id": station_id, "first_year": years[0], "last_year": years[1]}
            for station_id, years in sorted(inventory.items())
        ],
    }
    denominator_path.parent.mkdir(parents=True, exist_ok=True)
    denominator_path.write_text(
        json.dumps(denominator, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    frozen.append(
        FrozenObject(
            source_id="NCEI_GHCND_PRCP_DENOMINATOR",
            url="derived://ghcnd-stations+ghcnd-inventory",
            path=str(denominator_path),
            bytes=denominator_path.stat().st_size,
            sha256=sha256_file(denominator_path),
            retrieved_utc=datetime.now(timezone.utc).isoformat(),
        )
    )
    return frozen, denominator


def freeze_usdm(root: Path) -> tuple[list[FrozenObject], dict[str, Any]]:
    frozen: list[FrozenObject] = []
    paths: list[Path] = []
    for year, url in USDM_ANNUAL_URLS.items():
        path = root / "usdm" / f"{year}_USDM_GML.zip"
        paths.append(path)
        frozen.append(freeze_url(f"USDM_GML_{year}", url, path))
    closure = assert_usdm_archive_closure(paths)
    return frozen, closure


def write_manifest(
    root: Path,
    frozen: list[FrozenObject],
    ncei: dict[str, Any] | None,
    usdm: dict[str, Any] | None,
    failures: list[dict[str, str]],
) -> Path:
    manifest = {
        "schema_version": "aguayluz.drought-denominator-freeze/v0.1",
        "research_window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "objects": [asdict(item) for item in frozen],
        "ncei_denominator": ncei,
        "usdm_closure": usdm,
        "usgs_request_plan": build_usgs_request_plan(),
        "failures": failures,
        "certification": "complete" if not failures and ncei and usdm else "incomplete",
    }
    path = root / "freeze_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ncei", action="store_true")
    parser.add_argument("--usdm", action="store_true")
    args = parser.parse_args()
    if not (args.ncei or args.usdm):
        parser.error("select at least one acquisition family: --ncei and/or --usdm")

    root = args.output.resolve()
    frozen: list[FrozenObject] = []
    failures: list[dict[str, str]] = []
    ncei_result: dict[str, Any] | None = None
    usdm_result: dict[str, Any] | None = None

    if args.ncei:
        try:
            objects, ncei_result = freeze_ncei(root)
            frozen.extend(objects)
        except Exception as exc:
            failures.append(
                {"family": "ncei", "error_type": type(exc).__name__, "error": str(exc)}
            )
    if args.usdm:
        try:
            objects, usdm_result = freeze_usdm(root)
            frozen.extend(objects)
        except Exception as exc:
            failures.append(
                {"family": "usdm", "error_type": type(exc).__name__, "error": str(exc)}
            )

    manifest = write_manifest(root, frozen, ncei_result, usdm_result, failures)
    print(manifest)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
