from __future__ import annotations

import pytest
from desktop import setup


def test_resolve_python_prefers_supported_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup.shutil, "which", lambda name: f"/bin/{name}")
    versions = {
        "/bin/python3.12": "3.13",
        "/bin/python3.11": "3.11",
    }
    monkeypatch.setattr(
        setup.subprocess,
        "check_output",
        lambda command, **_kwargs: versions[command[0]],
    )

    assert setup.resolve_python_executable() == "/bin/python3.11"


def test_resolve_python_rejects_only_unsupported_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(setup.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(setup.subprocess, "check_output", lambda *_args, **_kwargs: "3.13")

    with pytest.raises(SystemExit, match="3.10–3.12"):
        setup.resolve_python_executable()
