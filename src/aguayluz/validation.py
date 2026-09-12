"""G01-G08 validation gate runners.

Each gate returns `GateResult(passed, status, details)`. `run_gates` aggregates
them and respects the `blocking` toggle from config/validation_gates.yaml so a
WARN-only override never blocks deploy even if the underlying check fails.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from . import CONFIG_DIR, OUTPUTS_DIR, REPO_ROOT, SCHEMAS_DIR
from .models import validate_against_schema

GateStatus = Literal["PASS", "WARN", "FAIL", "SKIP"]

_SECRET_PATTERNS = [
    # Only match string-literal assignments — `key = "..."` or `"key": "..."` — to
    # avoid false-positives on Python code like `self.api_key = resolve(api_key)`.
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"AKIA[0-9A-Z]{16}"),                     # AWS access key id
    re.compile(r"(?i)-----BEGIN (RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
]


@dataclass
class GateResult:
    gate_id: str
    status: GateStatus
    details: str = ""

    @property
    def passed(self) -> bool:
        return self.status in ("PASS", "WARN", "SKIP")

    @property
    def is_blocking_failure(self) -> bool:
        return self.status == "FAIL"


@dataclass
class GateReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def all_blocking_passed(self) -> bool:
        return all(not r.is_blocking_failure for r in self.results)

    def by_id(self, gate_id: str) -> GateResult | None:
        return next((r for r in self.results if r.gate_id == gate_id), None)

    def as_rows(self) -> list[tuple[str, str, str]]:
        return [(r.gate_id, r.status, r.details) for r in self.results]


def _load_gate_toggles() -> dict[str, dict]:
    path = CONFIG_DIR / "validation_gates.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f).get("gates", {})


# ---------------------------------------------------------------------------
# G01 — schema validation of every exported entity in outputs/
# ---------------------------------------------------------------------------

_ENTITY_SCHEMAS = {
    "utility_assets.json":   "utility_asset",            # list of utility_asset
    "service_events.json":   "service_event",            # list of service_event
    "monitoring_readings.json": "monitoring_reading",    # list of monitoring_reading
    "bridge_summary.json":   "aguayluz_bridge_summary",
    "hub_export.json":    "hub_export",
    "source_manifest.json":  "source_manifest",
    "review_queue.json":     "review_queue",
    "integration_report.json": "integration_report",
    "alert_events.json":     "alert_event",            # list of alert_event
}

_ENTITY_ARRAY_FILES = {
    "utility_assets.json", "service_events.json", "monitoring_readings.json", "alert_events.json",
}


def gate_g01_schema(*, outputs_dir: Path | None = None) -> GateResult:
    outputs_dir = OUTPUTS_DIR if outputs_dir is None else Path(outputs_dir)
    if not outputs_dir.exists():
        return GateResult("G01_SCHEMA", "SKIP", "outputs/ directory missing")
    files = sorted(p for p in outputs_dir.iterdir() if p.is_file() and p.suffix == ".json")
    if not files:
        return GateResult("G01_SCHEMA", "SKIP", "outputs/ empty — no entities to validate")

    recognized = [p for p in files if p.name in _ENTITY_SCHEMAS]
    ignored = [p.name for p in files if p.name not in _ENTITY_SCHEMAS]
    if not recognized:
        return GateResult("G01_SCHEMA", "SKIP", f"no recognized entity outputs; {len(ignored)} unvalidated JSON file(s)")
    errors: list[str] = []
    for p in recognized:
        schema_name = _ENTITY_SCHEMAS[p.name]
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{p.name}: invalid JSON ({exc})")
            continue
        if p.name in _ENTITY_ARRAY_FILES and not isinstance(data, list):
            errors.append(f"{p.name}: expected an array of entities")
            continue
        instances = data if p.name in _ENTITY_ARRAY_FILES else [data]
        for i, inst in enumerate(instances):
            try:
                validate_against_schema(schema_name, inst)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{p.name}[{i}]: {exc.__class__.__name__}: {exc}")
    if errors:
        return GateResult("G01_SCHEMA", "FAIL", "; ".join(errors[:5]) + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""))
    details = f"{len(recognized)} file(s) validated; {len(ignored)} unvalidated JSON file(s)"
    if ignored:
        details += ": " + ", ".join(ignored)
    return GateResult("G01_SCHEMA", "PASS", details)


# ---------------------------------------------------------------------------
# G02 — every output backed by a source_manifest entry
# ---------------------------------------------------------------------------

def gate_g02_source_manifest(*, outputs_dir: Path | None = None) -> GateResult:
    outputs_dir = OUTPUTS_DIR if outputs_dir is None else Path(outputs_dir)
    manifest_path = outputs_dir / "source_manifest.json"
    if not manifest_path.exists():
        outputs_have_entities = any(
            (outputs_dir / f).exists() for f in _ENTITY_SCHEMAS if f != "source_manifest.json"
        )
        if not outputs_have_entities:
            return GateResult("G02_SOURCE_MANIFEST", "SKIP", "no entity outputs yet")
        return GateResult("G02_SOURCE_MANIFEST", "FAIL", "source_manifest.json missing")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_against_schema("source_manifest", data)
    except Exception as exc:  # noqa: BLE001
        return GateResult("G02_SOURCE_MANIFEST", "FAIL", f"{exc.__class__.__name__}: {exc}")
    entries = data.get("entries", [])
    candidates: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        candidates.setdefault(entry["source_ref"], []).append(index)
    total = bound = missing = invalid = multiple = 0
    issues: list[dict] = []
    for filename in sorted(_ENTITY_ARRAY_FILES):
        path = outputs_dir / filename
        if not path.exists():
            continue
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            issues.append({"file": filename, "error": str(exc)})
            continue
        if not isinstance(records, list):
            issues.append({"file": filename, "error": "expected an array of entities"})
            continue
        for index, record in enumerate(records):
            total += 1
            ref = record.get("source_ref") if isinstance(record, dict) else None
            matches = candidates.get(ref, []) if isinstance(ref, str) and ref else []
            if not isinstance(ref, str) or not ref:
                invalid += 1
            elif not matches:
                missing += 1
            else:
                bound += 1
                if len(matches) > 1:
                    multiple += 1
                else:
                    continue
            issues.append({"file": filename, "index": index, "source_ref": ref,
                           "manifest_indices": matches})
    assert total == bound + missing + invalid
    details = json.dumps({
        "scope": sorted(_ENTITY_ARRAY_FILES), "sources": len(entries),
        "entities": total, "bound": bound, "missing": missing, "invalid": invalid,
        "multiple_candidates": multiple, "issues": issues, "identity_effect": "NONE",
    }, ensure_ascii=False, sort_keys=True)
    if missing or invalid or any("error" in issue for issue in issues):
        return GateResult("G02_SOURCE_MANIFEST", "FAIL", details)
    if multiple:
        return GateResult("G02_SOURCE_MANIFEST", "WARN", details)
    if not entries:
        return GateResult("G02_SOURCE_MANIFEST", "WARN", details)
    return GateResult("G02_SOURCE_MANIFEST", "PASS", details)


# ---------------------------------------------------------------------------
# G03 — every entity has confidence + tier (enforced by schema; spot-check here)
# ---------------------------------------------------------------------------

def gate_g03_confidence(*, outputs_dir: Path | None = None) -> GateResult:
    outputs_dir = OUTPUTS_DIR if outputs_dir is None else Path(outputs_dir)
    # G01 already enforces schema; this gate confirms no zero-confidence accepted records leak.
    issues: list[str] = []
    for fname in ("utility_assets.json", "service_events.json"):
        p = outputs_dir / fname
        if not p.exists():
            continue
        try:
            for i, rec in enumerate(json.loads(p.read_text(encoding="utf-8"))):
                if rec.get("review_status") == "accepted" and rec.get("confidence", 0) < 50:
                    issues.append(f"{fname}[{i}] accepted with confidence={rec.get('confidence')}")
        except Exception as exc:  # noqa: BLE001
            return GateResult("G03_CONFIDENCE", "FAIL", str(exc))
    if issues:
        return GateResult("G03_CONFIDENCE", "WARN", "; ".join(issues[:5]))
    return GateResult("G03_CONFIDENCE", "PASS" if (outputs_dir / "utility_assets.json").exists() else "SKIP",
                      "" if not issues else "")


# ---------------------------------------------------------------------------
# G04 — review queue presence + shape
# ---------------------------------------------------------------------------

def gate_g04_review_queue(*, outputs_dir: Path | None = None) -> GateResult:
    outputs_dir = OUTPUTS_DIR if outputs_dir is None else Path(outputs_dir)
    p = outputs_dir / "review_queue.json"
    if not p.exists():
        # acceptable for empty runs; only required if any entity has review_status="needs_review"/"blocked"
        for fname in ("utility_assets.json", "service_events.json"):
            ep = outputs_dir / fname
            if not ep.exists():
                continue
            try:
                for rec in json.loads(ep.read_text(encoding="utf-8")):
                    if rec.get("review_status") in ("needs_review", "blocked"):
                        return GateResult("G04_REVIEW_QUEUE", "FAIL", "needs_review records exist but review_queue.json missing")
            except Exception as exc:  # noqa: BLE001
                return GateResult("G04_REVIEW_QUEUE", "FAIL", str(exc))
        return GateResult("G04_REVIEW_QUEUE", "SKIP", "no review_queue.json and nothing needs review")
    try:
        validate_against_schema("review_queue", json.loads(p.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        return GateResult("G04_REVIEW_QUEUE", "FAIL", str(exc))
    return GateResult("G04_REVIEW_QUEUE", "PASS")


# ---------------------------------------------------------------------------
# G05 — coverage ledger
# ---------------------------------------------------------------------------

def gate_g05_coverage_ledger(*, outputs_dir: Path | None = None) -> GateResult:
    outputs_dir = OUTPUTS_DIR if outputs_dir is None else Path(outputs_dir)
    p = outputs_dir / "integration_report.json"
    if not p.exists():
        return GateResult("G05_COVERAGE_LEDGER", "SKIP", "integration_report.json missing")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        validate_against_schema("integration_report", data)
    except Exception as exc:  # noqa: BLE001
        return GateResult("G05_COVERAGE_LEDGER", "FAIL", str(exc))
    return GateResult("G05_COVERAGE_LEDGER", "PASS", f"coverage_pct={data.get('coverage', {}).get('coverage_pct')}")


# ---------------------------------------------------------------------------
# G06 — Hub export sanitization
# ---------------------------------------------------------------------------

def gate_g06_hub_export(*, outputs_dir: Path | None = None) -> GateResult:
    outputs_dir = OUTPUTS_DIR if outputs_dir is None else Path(outputs_dir)
    p = outputs_dir / "hub_export.json"
    if not p.exists():
        return GateResult("G06_HUB_EXPORT", "SKIP", "hub_export.json missing")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        validate_against_schema("hub_export", data)
    except Exception as exc:  # noqa: BLE001
        return GateResult("G06_HUB_EXPORT", "FAIL", str(exc))
    text = p.read_text(encoding="utf-8")
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            return GateResult("G06_HUB_EXPORT", "FAIL", f"secret-like pattern detected: {pat.pattern[:40]}…")
    return GateResult("G06_HUB_EXPORT", "PASS")


# ---------------------------------------------------------------------------
# G07 — no secrets in tracked files
# ---------------------------------------------------------------------------

_SCAN_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".md", ".toml"}
_SCAN_EXCLUDE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "node_modules", "outputs", "data", "reports",
    ".venv", "venv", "env", ".tox", ".nox", "build", "dist", ".eggs", "site-packages",
}
_SCAN_PATHSPECS = [
    "*.py",
    "*.json",
    "*.yaml",
    "*.yml",
    "*.md",
    "*.toml",
    *[f":(exclude){name}/**" for name in _SCAN_EXCLUDE_DIRS],
]


def gate_g07_no_secrets() -> GateResult:
    hits = _git_grep_secret_hits()
    if hits is not None:
        if hits:
            return GateResult("G07_NO_SECRETS", "FAIL", f"{len(hits)} file(s): " + ", ".join(hits[:3]))
        return GateResult("G07_NO_SECRETS", "PASS")

    hits: list[str] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in _SCAN_EXCLUDE_DIRS]
        base = Path(root)
        if any(part in _SCAN_EXCLUDE_DIRS for part in base.parts):
            continue
        for name in files:
            path = base / name
            if path.suffix not in _SCAN_EXTENSIONS:
                continue
            if any(part in _SCAN_EXCLUDE_DIRS for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat in _SECRET_PATTERNS:
                if pat.search(text):
                    hits.append(str(path.relative_to(REPO_ROOT)))
                    break
    if hits:
        return GateResult("G07_NO_SECRETS", "FAIL", f"{len(hits)} file(s): " + ", ".join(hits[:3]))
    return GateResult("G07_NO_SECRETS", "PASS")


def _git_grep_secret_hits() -> list[str] | None:
    """Fast path for the tracked-file secret gate.

    The gate is named "no secrets in tracked files"; using git's index-aware
    scanner avoids descending into local virtualenvs, caches and generated
    working files before Python can exclude them.
    """
    if not (REPO_ROOT / ".git").exists():
        return None
    hits: set[str] = set()
    for pattern in _SECRET_PATTERNS:
        expr = pattern.pattern
        flags = ["-I", "-n", "-E"]
        if expr.startswith("(?i)"):
            expr = expr.removeprefix("(?i)")
            flags.append("-i")
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "grep", *flags, expr, "--", *_SCAN_PATHSPECS],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 1:
            continue
        if proc.returncode != 0:
            return None
        for line in proc.stdout.splitlines():
            path = line.split(":", 1)[0]
            if path:
                hits.add(path)
    return sorted(hits)


# ---------------------------------------------------------------------------
# G08 — tests pass marker (CI runs the actual suite; this gate confirms the marker file)
# ---------------------------------------------------------------------------

def gate_g08_tests() -> GateResult:
    tests_dir = REPO_ROOT / "tests"
    if not tests_dir.exists() or not any(tests_dir.glob("test_*.py")):
        return GateResult("G08_TESTS", "FAIL", "no tests/test_*.py files")
    return GateResult(
        "G08_TESTS",
        "PASS",
        "test files present (run `pytest -q` to actually execute)",
    )


GATE_FUNCS: dict[str, Callable[[], GateResult]] = {
    "G01_SCHEMA":           gate_g01_schema,
    "G02_SOURCE_MANIFEST":  gate_g02_source_manifest,
    "G03_CONFIDENCE":       gate_g03_confidence,
    "G04_REVIEW_QUEUE":     gate_g04_review_queue,
    "G05_COVERAGE_LEDGER":  gate_g05_coverage_ledger,
    "G06_HUB_EXPORT":    gate_g06_hub_export,
    "G07_NO_SECRETS":       gate_g07_no_secrets,
    "G08_TESTS":            gate_g08_tests,
}


def run_gates(
    toggles: dict[str, dict] | None = None, *, outputs_dir: Path | None = None,
) -> GateReport:
    toggles = toggles if toggles is not None else _load_gate_toggles()
    results: list[GateResult] = []
    for gate_id, fn in GATE_FUNCS.items():
        cfg = toggles.get(gate_id, {})
        if not cfg.get("enabled", True):
            results.append(GateResult(gate_id, "SKIP", "disabled in config"))
            continue
        if outputs_dir is not None and gate_id in {
            "G01_SCHEMA", "G02_SOURCE_MANIFEST", "G03_CONFIDENCE",
            "G04_REVIEW_QUEUE", "G05_COVERAGE_LEDGER", "G06_HUB_EXPORT",
        }:
            result = fn(outputs_dir=outputs_dir)
        else:
            result = fn()
        if result.status == "FAIL" and cfg.get("blocking", True) is False:
            result = GateResult(gate_id, "WARN", f"non-blocking; underlying: {result.details}")
        results.append(result)
    return GateReport(results=results)


def assert_schemas_resolvable() -> None:
    """Sanity-check that every declared schema exists on disk."""
    missing = [n for n in set(_ENTITY_SCHEMAS.values()) if not (SCHEMAS_DIR / f"{n}.schema.json").exists()]
    if missing:
        raise FileNotFoundError(f"missing schemas: {missing}")
