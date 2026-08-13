from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TransportReceipt:
    backend: str
    backend_version: str
    requested_url: str
    final_url: str
    http_status: int | None
    etag: str | None
    last_modified: str | None
    bytes: int


class TransportError(RuntimeError):
    pass


def _copy_offline(source: Path, destination: Path, requested_url: str) -> TransportReceipt:
    if not source.is_file():
        raise TransportError(f"offline source missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return TransportReceipt(
        backend="offline",
        backend_version="filesystem",
        requested_url=requested_url,
        final_url=source.resolve().as_uri(),
        http_status=None,
        etag=None,
        last_modified=None,
        bytes=destination.stat().st_size,
    )


def _native(url: str, destination: Path, timeout: int) -> TransportReceipt:
    request = urllib.request.Request(
        url, headers={"User-Agent": "aguayluz-pr-drought-mgvb/0.1"}
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        with destination.open("wb") as target:
            shutil.copyfileobj(response, target, length=1024 * 1024)
        return TransportReceipt(
            backend="urllib",
            backend_version="python-stdlib",
            requested_url=url,
            final_url=response.geturl(),
            http_status=getattr(response, "status", None),
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
            bytes=destination.stat().st_size,
        )


def _cli(name: str, url: str, destination: Path, timeout: int) -> TransportReceipt:
    executable = shutil.which(name)
    if executable is None:
        raise TransportError(f"{name} unavailable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if name == "curl":
        command = [
            executable, "--fail", "--location", "--silent", "--show-error",
            "--max-time", str(timeout), "--output", str(destination), url,
        ]
    else:
        command = [
            executable, "--quiet", "--timeout", str(timeout),
            "--output-document", str(destination), url,
        ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        raise TransportError(
            f"{name} failed rc={completed.returncode}: {completed.stderr.strip()}"
        )
    version = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, check=False
    ).stdout.splitlines()[0]
    return TransportReceipt(
        backend=name,
        backend_version=version,
        requested_url=url,
        final_url=url,
        http_status=None,
        etag=None,
        last_modified=None,
        bytes=destination.stat().st_size,
    )


def acquire(
    url: str,
    destination: Path,
    *,
    offline_source: Path | None = None,
    timeout: int = 120,
) -> TransportReceipt:
    if offline_source is not None:
        return _copy_offline(offline_source, destination, url)

    failures: list[str] = []
    try:
        return _native(url, destination, timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        destination.unlink(missing_ok=True)
        failures.append(f"urllib:{type(exc).__name__}:{exc}")

    for backend in ("curl", "wget"):
        try:
            return _cli(backend, url, destination, timeout)
        except (TransportError, OSError) as exc:
            destination.unlink(missing_ok=True)
            failures.append(f"{backend}:{type(exc).__name__}:{exc}")

    raise TransportError("transport_blocked: " + " | ".join(failures))
