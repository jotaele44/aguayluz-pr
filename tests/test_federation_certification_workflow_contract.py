from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "federation-certification-evidence.yml"


def test_certification_workflow_generates_once_then_quarantines_and_freezes():
    text = WORKFLOW.read_text(encoding="utf-8")

    export_token = "python scripts/federation_export.py"
    quarantine_token = "python scripts/enforce_federation_review_quarantine.py"
    scope_token = "python scripts/write_federation_spatial_scope_receipt.py"
    finalize_token = "python scripts/finalize_federation_outputs.py"
    freeze_token = "python scripts/freeze_federation_runtime.py"
    hub_token = "validate_federation_runtime_package.py"

    assert text.count(export_token) == 1
    assert text.index(export_token) < text.index(quarantine_token)
    assert text.index(quarantine_token) < text.index(scope_token)
    assert text.index(scope_token) < text.index(finalize_token)
    assert text.index(finalize_token) < text.index(freeze_token)
    assert text.index(freeze_token) < text.index(hub_token)


def test_thehub_consumer_is_pinned_to_exact_commit_not_branch():
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"repository:\s*jotaele44/thehub-pr\s*\n\s*ref:\s*([0-9a-f]{40})",
        text,
    )
    assert match, "TheHub checkout must be pinned to an exact 40-hex commit"
    assert match.group(1) == "b3f2461d155f81b2d95ca1057c4f57343e18bb35"


def test_audit_only_and_negative_certification_paths_are_both_executed():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "THEHUB AUDIT-ONLY EXACT-BYTE PASS / NON-PROMOTABLE" in text
    assert "THEHUB CERTIFICATION REJECTION PASS" in text
    assert "--certification" in text
    assert 'assert payload["promotable"] is False' in text


def test_scope_and_quarantine_receipts_are_inside_uploaded_evidence_plane():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "outputs/" in text
    assert "governance/federation_spatial_certification_scope_v1.json" in text
    assert "artifacts/federation_certification/" in text
