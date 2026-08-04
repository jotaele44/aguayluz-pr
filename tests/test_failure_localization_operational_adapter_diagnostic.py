from __future__ import annotations

import runpy
from pathlib import Path

HELPERS = runpy.run_path(
    str(Path(__file__).with_name("test_failure_localization_operational_adapters.py"))
)


def test_operational_adapter_shared_failure_diagnostic(tmp_path):
    _, _, run = HELPERS["replay"](tmp_path, "known_break")
    assert run["status"] != "fail_closed", " | ".join(run["blockers"])
