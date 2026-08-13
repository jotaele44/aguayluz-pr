from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.drought_resilience.freeze_denominators import (
    _next_href,
    parse_ghcnd_pr_station_ids,
    parse_ghcnd_prcp_inventory,
    sha256_file,
    verify_replay,
)


def test_ncei_pr_station_and_prcp_overlap_selection():
    stations = (
        "RQC00660000  18.0000  -66.0000   10.0 PR TEST STATION                         \n"
        "USW00000000  40.0000  -75.0000   10.0 PA OTHER STATION                        \n"
    )
    ids = parse_ghcnd_pr_station_ids(stations)
    assert ids == {"RQC00660000"}

    inventory = (
        "RQC00660000  18.0000  -66.0000 PRCP 1900 2020\n"
        "RQC00660000  18.0000  -66.0000 TMAX 1900 2020\n"
    )
    selected = parse_ghcnd_prcp_inventory(inventory, ids)
    assert selected == {"RQC00660000": (1900, 2020)}


def test_ncei_prcp_selection_excludes_nonoverlap():
    ids = {"RQC00660000"}
    inventory = "RQC00660000  18.0000  -66.0000 PRCP 1900 2010\n"
    assert parse_ghcnd_prcp_inventory(inventory, ids) == {}


def test_ogc_next_link_is_explicit_only():
    assert _next_href({"links": [{"rel": "next", "href": "https://example.test/page2"}]}) == "https://example.test/page2"
    assert _next_href({"links": [{"rel": "self", "href": "https://example.test/page1"}]}) is None


def test_replay_requires_exact_byte_identity(tmp_path: Path):
    root = tmp_path
    data = b"authoritative-bytes\n"
    import hashlib

    digest = hashlib.sha256(data).hexdigest()
    path = root / "objects" / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    objects = [{
        "source_id": "X",
        "object_path": str(path.relative_to(root)),
        "bytes": len(data),
        "sha256": digest,
    }]
    result = verify_replay(root, objects)
    assert result == {"status": "replay_pass", "network_required": False, "verified_objects": 1}
    path.write_bytes(b"mutated\n")
    with pytest.raises(ValueError, match="replay identity mismatch"):
        verify_replay(root, objects)


def test_manifest_hash_helper_is_content_bound(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"a": 1}, sort_keys=True) + "\n")
    first = sha256_file(path)
    path.write_text(json.dumps({"a": 2}, sort_keys=True) + "\n")
    assert sha256_file(path) != first
