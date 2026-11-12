"""Runtime build-identity resolution for packaged AguaYLuz applications."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

BUILD_IDENTITY_SCHEMA = "aguayluz.build-identity/v1"
_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")


@dataclass(frozen=True)
class BuildIdentity:
    sha: str | None
    state: str
    embedded_sha: str | None
    env_sha: str | None
    error: str | None = None


def valid_commit_sha(value: str) -> bool:
    return bool(_SHA_RE.fullmatch(value))


def _embedded_identity(path: Path) -> tuple[str | None, str, str | None]:
    if not path.is_file():
        return None, "MISSING", None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None, "INVALID", "BUILD_METADATA_UNREADABLE"
    if not isinstance(payload, dict):
        return None, "INVALID", "BUILD_METADATA_NOT_OBJECT"
    if payload.get("schema_version") != BUILD_IDENTITY_SCHEMA:
        return None, "INVALID", "BUILD_METADATA_SCHEMA_MISMATCH"
    sha = str(payload.get("git_sha") or "").strip().lower()
    if not valid_commit_sha(sha):
        return None, "INVALID", "BUILD_METADATA_SHA_INVALID"
    return sha, "VALID", None


def resolve_build_identity(
    metadata_path: Path,
    env_names: Iterable[str],
) -> BuildIdentity:
    embedded_sha, embedded_state, embedded_error = _embedded_identity(metadata_path)
    if embedded_state == "INVALID":
        return BuildIdentity(
            sha=None,
            state="INVALID_METADATA",
            embedded_sha=None,
            env_sha=None,
            error=embedded_error,
        )

    env_values: list[tuple[str, str]] = []
    for name in env_names:
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        if not valid_commit_sha(raw):
            return BuildIdentity(
                sha=None,
                state="INVALID_ENV",
                embedded_sha=embedded_sha,
                env_sha=None,
                error=f"INVALID_ENV_SHA:{name}",
            )
        env_values.append((name, raw.lower()))

    distinct_env = sorted({value for _, value in env_values})
    if len(distinct_env) > 1:
        return BuildIdentity(
            sha=None,
            state="CONTRADICTION",
            embedded_sha=embedded_sha,
            env_sha=None,
            error="BUILD_ENV_SHA_CONTRADICTION",
        )

    env_sha = distinct_env[0] if distinct_env else None
    if embedded_sha and env_sha and embedded_sha != env_sha:
        return BuildIdentity(
            sha=None,
            state="CONTRADICTION",
            embedded_sha=embedded_sha,
            env_sha=env_sha,
            error="EMBEDDED_ENV_SHA_MISMATCH",
        )

    if embedded_sha:
        return BuildIdentity(
            sha=embedded_sha,
            state="EMBEDDED_CORROBORATED" if env_sha else "EMBEDDED",
            embedded_sha=embedded_sha,
            env_sha=env_sha,
        )
    if env_sha:
        return BuildIdentity(
            sha=env_sha,
            state="ENV_ONLY",
            embedded_sha=None,
            env_sha=env_sha,
        )
    return BuildIdentity(
        sha=None,
        state="MISSING",
        embedded_sha=None,
        env_sha=None,
        error="BUILD_IDENTITY_MISSING",
    )
