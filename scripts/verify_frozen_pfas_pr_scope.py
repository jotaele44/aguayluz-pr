"""CI-only verification of a passed frozen EPA artifact; no mutable acquisition.

National archive difference and Puerto Rico row equivalence are separate states.
The committed canonical PR denominator is checked and never replaced by this job.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

BUNDLE_SHA256 = "312c47f198ed7b749a7acb50058878f06763ed680d0fb6e507d85f59fc86b797"
OLD_ARCHIVE = "4845eb3abf34d61d7d239e26a815c69b21e39d249840243d266274b5b5d73aaa"
NEW_ARCHIVE = "007ee5f6a19dd8f1dac682ded23bcd3de72c8c5f49487dbf181334091bd35d96"
OLD_TSV = "ac40d8d67f7343832e0b11d78c892e3a6cdd44fe4d0b0892407347d4400b80c5"


def zip_manifest(raw: bytes) -> list[dict]:
    """Hash each unique file member using its ZipInfo; never choose by name."""
    rows = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = [i.filename for i in z.infolist()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP member paths")
        for info in z.infolist():
            if info.is_dir():
                continue  # Payload scope is file members; directories carry no source rows.
            digest = hashlib.sha256()
            with z.open(info) as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
            rows.append(
                {"path": info.filename, "size": info.file_size, "sha256": digest.hexdigest()}
            )
    return sorted(rows, key=lambda row: row["path"])


def compare_archives(a: bytes, b: bytes) -> dict:
    """Compare bytes, file-member/path multiplicity, and payload multisets."""
    am, bm = zip_manifest(a), zip_manifest(b)
    ac = Counter((r["path"], r["size"], r["sha256"]) for r in am)
    bc = Counter((r["path"], r["size"], r["sha256"]) for r in bm)
    ap = Counter((r["size"], r["sha256"]) for r in am)
    bp = Counter((r["size"], r["sha256"]) for r in bm)
    state = (
        "BYTE_IDENTICAL"
        if a == b
        else "PURE_RECOMPRESSION"
        if ac == bc
        else "SAME_PAYLOADS_DIFFERENT_PATHS"
        if ap == bp
        else "DISTINCT_PAYLOADS"
    )
    return {
        "classification": state,
        "baseline_members": am,
        "observed_members": bm,
        "payload_multisets_equal": ap == bp,
        "intersection": sum((ac & bc).values()),
        "a_only": sum((ac - bc).values()),
        "b_only": sum((bc - ac).values()),
        "union": sum((ac | bc).values()),
        "symmetric_difference": sum((ac - bc).values()) + sum((bc - ac).values()),
    }


def table(raw: bytes) -> tuple[list[str], list[tuple[str, ...]]]:
    """Inspect the generated TSV schema and preserve every raw field exactly."""
    import csv

    rows = list(
        csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), delimiter="\t", strict=True)
    )
    if not rows or not rows[0] or len(set(rows[0])) != len(rows[0]) or "PWSID" not in rows[0]:
        raise ValueError("invalid or duplicate TSV header")
    header = rows[0]
    if any(len(row) != len(header) for row in rows[1:]):
        raise ValueError("TSV positional field count differs")
    return header, [tuple(row) for row in rows[1:]]


def select_pr_source(raw_archive: bytes) -> tuple[list[str], Counter, dict]:
    """Re-derive PR whole rows from the frozen national member, preserving cp1252 strings."""
    with (
        zipfile.ZipFile(io.BytesIO(raw_archive)) as z,
        z.open("UCMR5_All_MA_WY.txt") as source,
        io.TextIOWrapper(source, encoding="cp1252", newline="") as text,
    ):
        # Inspected source is literal tab-delimited text: quote characters in
        # system names are data, not CSV quoting. Preserve them exactly.
        header = next(text).rstrip("\r\n").split("\t")
        if len(header) != len(set(header)) or "PWSID" not in header or "State" not in header:
            raise ValueError("source header invalid")
        pws_index, state_index = header.index("PWSID"), header.index("State")
        selected = Counter()
        total = retained = 0
        for line in text:
            row = line.rstrip("\r\n").split("\t")
            total += 1
            if len(row) != len(header) or row == header:
                raise ValueError("source row/header defect")
            by_id = row[pws_index].startswith("PR")
            by_state = row[state_index] == "PR"
            if by_id != by_state:
                raise ValueError("source PR identifier/state contradiction")
            if by_id:
                selected[tuple(row)] += 1
                retained += 1

    return (
        header,
        selected,
        {
            "source": total,
            "retained": retained,
            "excluded": total - retained,
            "encoding": "cp1252",
            "member": "UCMR5_All_MA_WY.txt",
        },
    )


def verify_bundle(bundle: bytes, canonical: bytes) -> dict:
    """Re-adjudicate the passed artifact independently and conserve the PR subset."""
    if hashlib.sha256(bundle).hexdigest() != BUNDLE_SHA256:
        raise ValueError("frozen evidence bundle differs")
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        names = [i.filename for i in z.infolist()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate artifact paths")
        old = z.read("historical/artifact/raw/ucmr5-occurrence-data-by-state.zip")
        new = z.read("raw/ucmr5-occurrence-data-by-state.zip")
        old_tsv = z.read("historical/artifact/derived/ucmr5_pr.tsv")
        new_tsv = z.read("derived/ucmr5_pr.tsv")
    if (
        hashlib.sha256(old).hexdigest() != OLD_ARCHIVE
        or hashlib.sha256(new).hexdigest() != NEW_ARCHIVE
    ):
        raise ValueError("source manifestation mismatch")
    if hashlib.sha256(canonical).hexdigest() != OLD_TSV or canonical != old_tsv:
        raise ValueError("canonical PR snapshot changed")
    archive_result = compare_archives(old, new)
    oh, old_rows = table(old_tsv)
    nh, new_rows = table(new_tsv)
    if oh != nh or len(oh) != 24:
        raise ValueError("PR positional schema differs")
    oc, nc = Counter(old_rows), Counter(new_rows)
    old_source_header, old_source_rows, old_source_counts = select_pr_source(old)
    new_source_header, new_source_rows, new_source_counts = select_pr_source(new)
    if (
        old_source_header != oh
        or new_source_header != nh
        or old_source_rows != oc
        or new_source_rows != nc
    ):
        raise ValueError("derived TSV does not match complete frozen source selection")
    idx = oh.index("PWSID")
    old_ids = {row[idx] for row in old_rows}
    new_ids = {row[idx] for row in new_rows}
    if (
        len(old_rows) != 21771
        or len(new_rows) != 21771
        or oc != nc
        or old_ids != new_ids
        or len(old_ids) != 99
    ):
        raise ValueError("PR row or identifier denominator changed")
    import re

    if any(not re.fullmatch(r"PR[0-9]{7}", value) for value in old_ids):
        raise ValueError("unexpected raw PWSID syntax")
    if archive_result["classification"] != "DISTINCT_PAYLOADS":
        raise ValueError("frozen national manifestation classification changed")
    return {
        "state": "PASS_FROZEN_PR_SCOPE_NATIONAL_DISTINCT",
        "scope": "Exact frozen PR row multiset and existing canonical TSV only; no live freshness or national equivalence claim",
        "bundle_sha256": BUNDLE_SHA256,
        "baseline_archive_sha256": OLD_ARCHIVE,
        "observed_archive_sha256": NEW_ARCHIVE,
        "archive": archive_result,
        "source_accounting": {"baseline": old_source_counts, "observed": new_source_counts},
        "headers": oh,
        "row_count": len(old_rows),
        "pwsid_count": len(old_ids),
        "row_multiset": {
            "intersection": sum((oc & nc).values()),
            "a_only": 0,
            "b_only": 0,
            "union": sum((oc | nc).values()),
            "symmetric_difference": 0,
        },
        "pwsid_set": {
            "intersection": len(old_ids & new_ids),
            "a_only": 0,
            "b_only": 0,
            "union": len(old_ids | new_ids),
            "symmetric_difference": 0,
        },
        "canonical_sha256": OLD_TSV,
        "canonical_replaced": False,
        "source_run_id": 39968848835,
        "source_artifact_id": 12508351665,
    }


if __name__ == "__main__":
    result = verify_bundle(
        Path(sys.argv[1]).read_bytes(), Path("data/pfas_ucmr5_pr.tsv").read_bytes()
    )
    target = Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(result["state"])
