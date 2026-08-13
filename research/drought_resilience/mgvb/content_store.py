from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    bytes: int
    object_path: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest(source: Path, store_root: Path) -> StoredObject:
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = sha256_file(source)
    target = store_root / "sha256" / digest[:2] / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256_file(target) != digest:
            raise ValueError(f"content-address collision/corruption: {target}")
    else:
        temporary = target.with_suffix(".partial")
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != digest:
            temporary.unlink(missing_ok=True)
            raise ValueError("copy digest mismatch")
        temporary.replace(target)
    return StoredObject(
        sha256=digest,
        bytes=source.stat().st_size,
        object_path=str(target),
    )


def verify(stored: StoredObject) -> None:
    path = Path(stored.object_path)
    if not path.is_file():
        raise ValueError(f"missing content-addressed object: {path}")
    if path.stat().st_size != stored.bytes:
        raise ValueError(f"byte length mismatch: {path}")
    if sha256_file(path) != stored.sha256:
        raise ValueError(f"sha256 mismatch: {path}")
