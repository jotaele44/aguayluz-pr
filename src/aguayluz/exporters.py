"""Base44 export envelope builder.

Pure I/O-free transformation: takes asset + event dicts, gate report, and
metadata in; returns a fully-validated dict ready to write as
`outputs/base44_export.json`.

Why centralize this here:
  - The envelope shape is dictated by AGUAYLUZ_PR_SKILL.md and the schema in
    schemas/base44_export.schema.json. Having a single builder means scripts
    don't drift from the contract.
  - The `Base44Export` Pydantic model re-validates the envelope against the
    schema on construction, so a malformed envelope never makes it to disk.
  - Sanitization (no api keys, no precise private-address targeting) is
    enforced at the summary text level. Records pulled in from upstream
    `utility_assets.json` are already sanitized by `mapping.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import Base44Export, ExportStatus

# Match string-literal secret assignments — same shape as the G07 scanner.
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
)


def _records_by_status(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"accepted": 0, "needs_review": 0, "rejected": 0, "blocked": 0}
    for r in records:
        status = r.get("review_status")
        if status in counts:
            counts[status] += 1
    return counts


def _confidence_avg(records: list[dict[str, Any]]) -> float:
    values = [r.get("confidence") for r in records if isinstance(r.get("confidence"), (int, float))]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 1)


def _envelope_status(gate_statuses: list[str]) -> ExportStatus:
    if any(s == "FAIL" for s in gate_statuses):
        return "FAIL"
    if any(s == "WARN" for s in gate_statuses):
        return "WARN"
    return "PASS"


def _assert_no_secrets(text: str) -> None:
    if _SECRET_PATTERN.search(text):
        raise ValueError(
            "sanitized_summary contains a key-shaped string — refuse to export. "
            "Strip the value before passing it to build_base44_envelope."
        )


def load_contradictions_from_report(report_path: Path | str) -> list[dict[str, Any]]:
    """Read `outputs/reconciliation_report.json` and project warn+critical findings
    into the Base44 envelope's `contradictions` shape.

    The reconciliation report is the source of truth — every envelope-refreshing
    script calls this so M8's findings survive M13/M15 rebuilds.
    """
    path = Path(report_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    findings = data.get("findings", []) if isinstance(data, dict) else []
    return [
        {
            "finding_id": f["finding_id"],
            "kind": f["kind"],
            "severity": f["severity"],
            "municipality": f.get("municipality"),
            "details": f.get("details"),
            "confidence": f.get("confidence"),
        }
        for f in findings
        if isinstance(f, dict) and f.get("severity") in ("warn", "critical")
    ]


def build_base44_envelope(
    *,
    assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    run_id: str,
    vector: str,
    coverage_pct: float,
    gate_statuses: list[str],
    sanitized_summary: str,
    source_manifest_path: str = "outputs/source_manifest.json",
    integration_report_path: str = "outputs/integration_report.json",
    top_findings: list[dict[str, Any]] | None = None,
    contradictions: list[dict[str, Any]] | None = None,
    gaps: list[str] | None = None,
    next_actions: list[str] | None = None,
    federation_handoffs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a Base44-export dict that round-trips through `Base44Export`.

    Caller is responsible for the gate report and the summary text; we enforce
    no-secrets in the summary as a tripwire.
    """
    _assert_no_secrets(sanitized_summary)

    record_counts = _records_by_status(assets + events)
    confidence_avg = _confidence_avg(assets + events)
    status = _envelope_status(gate_statuses)

    envelope = Base44Export(
        run_id=run_id,
        vector=vector,
        status=status,
        coverage_pct=float(coverage_pct),
        records_total=len(assets) + len(events),
        records_review=record_counts["needs_review"],
        records_blocked=record_counts["blocked"] + record_counts["rejected"],
        confidence_avg=confidence_avg,
        source_manifest_path=source_manifest_path,
        integration_report_path=integration_report_path,
        sanitized_summary=sanitized_summary,
        top_findings=top_findings or [],
        contradictions=contradictions or [],
        gaps=gaps or [],
        next_actions=next_actions or [],
        federation_handoffs=federation_handoffs or [],
    )
    return envelope.model_dump()
