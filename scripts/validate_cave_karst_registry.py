#!/usr/bin/env python3
"""Validate the canonical cave-and-karst registry and print a bounded receipt."""
from __future__ import annotations

import json

from aguayluz.cave_karst import load_default_registry, validate_registry


def main() -> int:
    report = validate_registry(**load_default_registry())
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
