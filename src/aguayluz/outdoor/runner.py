"""Shared run harness for the outdoor-condition ingests.

Every outdoor ingest does the same five things around its own parsing, in the same
order as ``scripts/ingest_nwps_gauges.py``:

1. read its registry entry from ``config/hydromet_sources.v1.json``;
2. acquire each response — live, or from ``--src`` offline — and freeze the exact bytes
   (:func:`aguayluz.hydromet.store.freeze_bytes`) *before* parsing;
3. build records/state rows and close source arithmetic, or fail closed;
4. merge through :func:`aguayluz.hydromet.store.apply_source_run` (prefix-scoped,
   integrity-checked) and rewrite the source's state file;
5. write a PASS receipt, or a FAIL receipt that keeps the last success.

A script supplies two callables: ``acquire(ctx)`` (calls :meth:`RunContext.get` once per
response) and ``build(ctx, responses)`` (pure). Offline, ``--src`` is either one file
(used for a single-response source) or a directory holding one file per response key.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import DATA_DIR
from ..hazard_plane import HazardRecord, HazardRelationship, Manifestation
from ..hydromet import USER_AGENT, store
from . import STATE_FILES, load_reference, state_path


class AcquisitionError(RuntimeError):
    """The source could not be acquired; becomes a FAIL receipt."""


@dataclass(frozen=True)
class Response:
    """One frozen source response."""

    key: str
    payload: bytes
    manifestation: Manifestation


@dataclass
class Built:
    """What one run produces. ``arithmetic`` must PASS or nothing is written."""

    arithmetic: dict[str, Any]
    state_rows: list[dict[str, Any]] = field(default_factory=list)
    records: list[HazardRecord] = field(default_factory=list)
    relationships: list[HazardRelationship] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)
    #: Manifestations the state rows point at (kept by the receipt).
    referenced: set[str] = field(default_factory=set)
    retain_event: Callable[[HazardRecord], bool] | None = None
    #: Printed on success.
    message: str = ""


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class RunContext:
    source_id: str
    source: dict[str, Any]
    args: argparse.Namespace
    now: datetime
    paths: store.HydrometPaths
    reference: dict[str, Any]
    authority: str
    system: str
    _client: Any = None
    responses: list[Response] = field(default_factory=list)
    #: Per-item acquisition failures a multi-request source tolerates (key -> error).
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def offline(self) -> bool:
        return self.args.src is not None

    def _offline_bytes(self, key: str) -> bytes:
        src: Path = self.args.src
        if src.is_dir():
            target = src / key
            if not target.is_file():
                raise AcquisitionError(f"offline response {key!r} missing from {src}")
            return target.read_bytes()
        return src.read_bytes()

    def _live_bytes(self, url: str, params: dict[str, Any] | None,
                    headers: dict[str, str] | None) -> tuple[bytes, dict[str, str]]:
        import httpx

        from ..http_retry import get_with_retry

        if self._client is None:
            self._client = httpx.Client(timeout=60, follow_redirects=True,
                                        headers={"User-Agent": USER_AGENT})
        response = get_with_retry(url, params=params, headers=headers, client=self._client)
        response.raise_for_status()
        return response.content, dict(response.headers)

    def get(self, url: str, *, key: str, params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None, record_id: str | None = None,
            extension: str = "json", redact_query: Iterable[str] = ()) -> Response:
        """Acquire one response and freeze it before anyone parses it.

        ``redact_query`` names query parameters (an API key) that must never reach a
        manifestation, a receipt or a log line.
        """
        try:
            if self.offline:
                payload, response_headers = self._offline_bytes(key), {}
            else:
                payload, response_headers = self._live_bytes(url, params, headers)
        except AcquisitionError:
            raise
        except Exception as exc:  # noqa: BLE001 - any transport/HTTP failure
            raise AcquisitionError(f"{key}: {_scrub(str(exc), params, redact_query)}") from exc
        shown = {k: v for k, v in (params or {}).items() if k not in set(redact_query)}
        query = "&".join(f"{k}={v}" for k, v in shown.items()) or None
        manifestation = store.freeze_bytes(
            self.source_id, payload,
            source_authority=self.authority,
            source_system=self.system,
            source_record_id=record_id or key,
            source_url=url,
            retrieval_query=query,
            retrieved_at=self.now,
            headers=response_headers,
            snapshot_dir=None if self.args.dry_run else self.paths.snapshot_dir(self.source_id),
            extension=extension,
        )
        response = Response(key, payload, manifestation)
        self.responses.append(response)
        return response

    def try_get(self, url: str, *, key: str, **kwargs: Any) -> Response | None:
        """Like :meth:`get`, but one item failing is recorded instead of raised."""
        try:
            return self.get(url, key=key, **kwargs)
        except AcquisitionError as exc:
            self.failures[key] = str(exc)[:300]
            return None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def _scrub(text: str, params: dict[str, Any] | None, names: Iterable[str]) -> str:
    for name in names:
        value = (params or {}).get(name)
        if value:
            text = text.replace(str(value), "***")
    return text


def base_parser(description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--src", type=Path,
                    help="offline input: one response file, or a directory of response files")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--reference", type=Path, default=None,
                    help="default data/reference/outdoor_reference.v1.json")
    ap.add_argument("--now", help="override the run clock (ISO 8601), for reproducible tests")
    ap.add_argument("--dry-run", action="store_true", help="fetch and build; write nothing")
    return ap


def run_ingest(
    *,
    source_id: str,
    authority: str,
    system: str,
    argv: list[str] | None,
    description: str,
    acquire: Callable[[RunContext], None],
    build: Callable[[RunContext, list[Response]], Built],
    parser: argparse.ArgumentParser | None = None,
    preflight: Callable[[argparse.Namespace], str | None] | None = None,
) -> int:
    """Run one outdoor ingest; returns the process exit code."""
    args = (parser or base_parser(description)).parse_args(argv)
    name = f"ingest_{source_id}"
    if preflight is not None:
        skip = preflight(args)
        if skip:
            # A missing credential is not a source failure: no receipt is written, so the
            # source reads NEVER (not FAILED) until it is configured.
            print(f"{name}: SKIPPED — {skip}")
            return 0
    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc).replace(microsecond=0)
    if now is None:
        print("--now is not a valid ISO 8601 timestamp", file=sys.stderr)
        return 2
    source = store.registry_source(source_id, store.load_source_registry(args.registry))
    if source is None:
        print(f"{source_id} missing from config/hydromet_sources.v1.json", file=sys.stderr)
        return 2
    paths = store.hydromet_paths(args.data_dir)
    try:
        reference = load_reference(args.reference)
    except ValueError as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return 2
    ctx = RunContext(source_id, source, args, now, paths, reference, authority, system)

    def fail(message: str) -> int:
        print(f"{name}: FAIL — {message}", file=sys.stderr)
        if not args.dry_run:
            store.record_receipt(source_id, status="FAIL", attempted_at=now,
                                 data_dir=paths.data_dir, error=message[:500])
        return 1

    try:
        acquire(ctx)
    except AcquisitionError as exc:
        return fail(str(exc))
    finally:
        ctx.close()
    try:
        built = build(ctx, ctx.responses)
    except (ValueError, KeyError, TypeError) as exc:
        return fail(f"response unparseable: {exc}")
    if built.arithmetic.get("state") != "PASS":
        return fail(f"source arithmetic does not close: {built.arithmetic}")

    # The NWS Hydromet page's source card shows one URL and one byte hash; give it the
    # response the state rows are built from (the product, for a listing + product pair).
    primary = ctx.responses[-1] if 0 < len(ctx.responses) <= 2 else None
    summary: dict[str, Any] = {
        "source_url": primary.manifestation.source_url if primary
        else next(iter((source.get("endpoints") or {}).values()), None),
        "byte_sha256": primary.manifestation.byte_sha256 if primary else None,
        "responses": [
            {"key": r.key, "byte_sha256": r.manifestation.byte_sha256,
             "manifestation_id": r.manifestation.manifestation_id}
            for r in ctx.responses
        ] if len(ctx.responses) <= 5 else {"count": len(ctx.responses)},
        "arithmetic": built.arithmetic,
        **({"acquisition_failures": dict(sorted(ctx.failures.items()))} if ctx.failures else {}),
        **built.counts,
    }
    if args.dry_run:
        print(json.dumps({"dry_run": True, **summary}, indent=2, sort_keys=True, default=str))
        return 0

    referenced = set(built.referenced)
    try:
        applied = store.apply_source_run(
            store.SourceRun(source_id, manifestations=[r.manifestation for r in ctx.responses],
                            records=built.records, relationships=built.relationships,
                            retain_event=built.retain_event),
            paths.data_dir,
            referenced_manifestation_ids=referenced,
        )
    except ValueError as exc:
        return fail(str(exc))
    if source_id in STATE_FILES:
        store.write_jsonl(state_path(source_id, paths.data_dir), built.state_rows)
    summary.update(applied)
    store.record_receipt(source_id, status="PASS", attempted_at=now, data_dir=paths.data_dir,
                         summary=summary, referenced_manifestation_ids=referenced)
    store.append_accounting({"source_id": source_id, "run_utc": iso(now),
                             "arithmetic": built.arithmetic}, paths.data_dir)
    print(built.message or f"{source_id}: {built.arithmetic['retained']}/"
          f"{built.arithmetic['source']} retained")
    return 0


__all__ = [
    "AcquisitionError",
    "Built",
    "Response",
    "RunContext",
    "base_parser",
    "iso",
    "parse_iso",
    "run_ingest",
]
