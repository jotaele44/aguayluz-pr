"""Stage an allowlisted, byte-verified reference snapshot for GUI parity tests.

Only four tracked canonical data files are copied into the per-run workspace.
The staging receipt binds source commit/blob IDs and source/staged SHA-256 values.
No source, operator data, or production path is written.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "aguayluz.gui-reference-staging/v1"
RECEIPT_NAME = ".gui-reference-staging.json"
LOCK_NAME = ".gui-reference-staging.lock"
ALLOWLIST = (
    ("cave_karst_assets.jsonl", "asset_id"),
    ("nwps_gauge_state.jsonl", "lid"),
    ("hydromet_receipts.json", None),
    ("hydromet_manifestations.jsonl", "manifestation_id"),
)
ALLOWED_DATA_NAMES = {name for name, _ in ALLOWLIST} | {RECEIPT_NAME}


def _git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _workspace_root() -> Path:
    raw = os.getenv("AGUAYLUZ_DATA_HOME", "").strip()
    if not raw:
        raise ValueError("AGUAYLUZ_DATA_HOME is required")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("AGUAYLUZ_DATA_HOME must be absolute")
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("workspace must be an existing, non-symlink directory")
    workspace = candidate.resolve(strict=True)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    if not workspace.is_relative_to(temp_root):
        raise ValueError("workspace must be inside the system temporary directory")
    if not workspace.name.startswith("aguayluz-gui-parity-"):
        raise ValueError("workspace does not have the GUI parity ownership prefix")
    return workspace


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    if path.is_symlink():
        raise ValueError("staging lock must not be a symlink")
    handle = path.open("a+b")
    acquired = False
    try:
        try:
            if os.name == "nt":
                handle.seek(0)
                if not handle.read(1):
                    handle.seek(0)
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise RuntimeError("another GUI reference staging run is active") from exc
        yield
    finally:
        if acquired:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _logical_count(name: str, payload: bytes, id_key: str | None) -> int:
    try:
        text = payload.decode("utf-8")
        if name == "hydromet_receipts.json":
            value = json.loads(text)
            if (
                not isinstance(value, dict)
                or value.get("schema_version") != "aguayluz.hydromet-receipts/v1"
                or not isinstance(value.get("sources"), dict)
            ):
                raise ValueError("receipt JSON does not match the declared schema")
            return len(value["sources"])

        rows = [
            json.loads(line)
            for line in text.splitlines()
            if line.strip()
        ]
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError("JSONL must contain non-empty object rows")
        if not id_key:
            raise ValueError("JSONL allowlist entry has no identity key")
        ids = [row.get(id_key) for row in rows]
        if any(not isinstance(value, str) or not value.strip() for value in ids):
            raise ValueError(f"rows require non-empty {id_key}")
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate {id_key} values")
        return len(rows)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid UTF-8 JSON data in {name}: {exc}") from exc


def _source_record(head: str, name: str, id_key: str | None) -> tuple[dict[str, object], bytes]:
    relative = f"data/{name}"
    source = REPO_ROOT / relative
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"canonical source is missing, non-regular, or symlinked: {relative}")

    status = _git("status", "--porcelain=v1", "--", relative).decode("utf-8").strip()
    if status:
        raise ValueError(f"canonical source differs from clean checkout state: {relative}")
    blob_sha = _git("rev-parse", f"HEAD:{relative}").decode("ascii").strip()
    committed = _git("cat-file", "blob", f"HEAD:{relative}")
    payload = source.read_bytes()
    if payload != committed:
        raise ValueError(f"working-tree bytes differ from committed source blob: {relative}")

    count = _logical_count(name, payload, id_key)
    digest = _sha256(payload)
    return (
        {
            "path": relative,
            "git_blob_sha": blob_sha,
            "source_sha256": digest,
            "staged_sha256": digest,
            "bytes": len(payload),
            "logical_count": count,
        },
        payload,
    )


def main() -> int:
    try:
        workspace = _workspace_root()
        with _exclusive_lock(workspace / LOCK_NAME):
            head = _git("rev-parse", "HEAD").decode("ascii").strip()
            data_dir = workspace / "data"
            if data_dir.is_symlink():
                raise ValueError("workspace data directory must not be a symlink")
            data_dir.mkdir(mode=0o700, exist_ok=True)
            if not data_dir.is_dir():
                raise ValueError("workspace data path is not a directory")

            sources = [
                _source_record(head, name, id_key)
                for name, id_key in ALLOWLIST
            ]
            expected = {
                "schema_version": SCHEMA,
                "authority_head": head,
                "files": [record for record, _ in sources],
            }
            receipt_bytes = (json.dumps(expected, sort_keys=True, indent=2) + "\n").encode("utf-8")

            for entry in data_dir.iterdir():
                if entry.name not in ALLOWED_DATA_NAMES:
                    raise ValueError(f"unexpected workspace data entry: {entry.name}")
                if entry.is_symlink() or not entry.is_file():
                    raise ValueError(f"staged data entries must be regular files: {entry.name}")

            receipt_path = data_dir / RECEIPT_NAME
            if receipt_path.exists() and receipt_path.read_bytes() != receipt_bytes:
                raise ValueError("existing staging receipt conflicts with current source snapshot")

            for record, payload in sources:
                destination = data_dir / Path(str(record["path"])).name
                if destination.exists() and destination.read_bytes() != payload:
                    raise ValueError(f"existing staged file conflicts; refusing overwrite: {destination.name}")

            # Preflight above is complete before any copy. Create only absent files.
            for record, payload in sources:
                destination = data_dir / Path(str(record["path"])).name
                if not destination.exists():
                    try:
                        with destination.open("xb") as handle:
                            handle.write(payload)
                            handle.flush()
                            os.fsync(handle.fileno())
                    except FileExistsError:
                        if destination.is_symlink() or destination.read_bytes() != payload:
                            raise ValueError(f"concurrent staged-file conflict: {destination.name}")
                staged = destination.read_bytes()
                if _sha256(staged) != record["staged_sha256"] or staged != payload:
                    raise ValueError(f"staged byte parity failed: {destination.name}")

            if not receipt_path.exists():
                try:
                    with receipt_path.open("xb") as handle:
                        handle.write(receipt_bytes)
                        handle.flush()
                        os.fsync(handle.fileno())
                except FileExistsError:
                    if receipt_path.is_symlink() or receipt_path.read_bytes() != receipt_bytes:
                        raise ValueError("concurrent staging receipt conflict")
            if receipt_path.is_symlink() or receipt_path.read_bytes() != receipt_bytes:
                raise ValueError("staging receipt failed final byte verification")

            actual = {entry.name for entry in data_dir.iterdir()}
            if actual != ALLOWED_DATA_NAMES:
                raise ValueError("staging directory does not exactly match the allowlist")

            print("GUI_REFERENCE_STAGING=PASS")
            print(f"AUTHORITY_HEAD={head}")
            print(f"FILES_STAGED={len(sources)}/{len(ALLOWLIST)}")
            for record, _ in sources:
                print(
                    f"FILE={record['path']} SHA256={record['source_sha256']} "
                    f"BYTES={record['bytes']} LOGICAL_COUNT={record['logical_count']}"
                )
            print(f"STAGING_RECEIPT_SHA256={_sha256(receipt_bytes)}")
            return 0
    except Exception as exc:
        print(f"GUI_REFERENCE_STAGING=FAIL_CLOSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
