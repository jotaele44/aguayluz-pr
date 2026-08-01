#!/usr/bin/env python3
"""Fail-closed certification checks for the Agua y Luz shadow water pipeline."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    schema_path = ROOT / "schemas/water-disruption/v0.1/aguayluz-water-incident.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validation = schema["$defs"]["validation"]
    require("allOf" in validation, "confirmed validation constraint missing")

    domain_path = ROOT / "server/backend/water_disruption.py"
    api_path = ROOT / "server/backend/water_disruption_api.py"
    app_path = ROOT / "server/backend/app.py"
    for path in (domain_path, api_path, app_path):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    domain = domain_path.read_text(encoding="utf-8")
    api = api_path.read_text(encoding="utf-8")
    app = app_path.read_text(encoding="utf-8")
    require("confidence_ignored_for_confirmation" in domain, "confidence-only promotion guard missing")
    require("authoritative_scope_match" in domain, "authority confirmation gate missing")
    require("independent_source_count >= 2 and reviewer_approved" in domain, "corroboration gate missing")
    require('shadow_mode.lower() != "true"' in api, "non-shadow intake rejection missing")
    require('"notifications_enabled": False' in api, "notifications guard missing")
    require('"production_promotion_enabled": False' in api, "promotion guard missing")
    require("app.include_router(water_disruption_router)" in app, "consumer router not mounted")
    print("AGUAYLUZ_WATER_SHADOW_CERTIFICATION=PASS")


if __name__ == "__main__":
    main()
