"""AguaYLuz's Launch Pad declaration (desktop/config.py).

The screen itself lives in the shared prii_desktop runtime; these tests keep the
declaration true to this repository. They skip when the installed runtime
predates the Launch Pad.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

launchpad = pytest.importorskip("prii_desktop.launchpad")

from desktop import config  # noqa: E402
from prii_desktop import DesktopConfig  # noqa: E402

ROOT = Path(config.REPO_ROOT)
BACKEND = ROOT / "server" / "backend"


def _spec():
    return launchpad.launchpad_spec(DesktopConfig.from_module(config))


def test_declaration_is_valid_and_sets_no_api_key():
    spec = _spec()
    assert spec is not None and spec.has_modes
    # Operator must not set API_SECRET_KEY: the dashboard only takes that key
    # by hand on the System page, so setting it here would lock the UI out.
    assert spec.operator.token_env is None
    assert "API_SECRET_KEY" not in {option.env for option in spec.options}


def test_start_pages_are_real_routes():
    routes = (ROOT / "dashboard/src/App.jsx").read_text()
    for page in _spec().start_pages:
        assert f'path="{page.route}"' in routes, page.route


def test_a_guest_is_allowed_no_write_because_none_is_a_pure_read():
    assert _spec().guest_allow == ()
    sources = "\n".join(path.read_text() for path in sorted(BACKEND.glob("*.py")))
    writes = re.findall(r"@(?:app|router)\.(post|put|patch|delete)\(", sources)
    # A new non-GET route must be classified: a read-only one needs an allow
    # entry in LAUNCHPAD["guest_guard"], otherwise update this count.
    assert sorted(writes) == ["patch"] * 2 + ["post"] * 14, writes


def test_options_bind_variables_the_backend_reads():
    code = (BACKEND / "main.py").read_text()
    for option in _spec().options:
        assert f'"{option.env}"' in code, option.env


def test_status_reads_the_selected_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv(config.DATA_ENV_VAR, str(tmp_path))
    rows = {row["label"]: row for row in config._launchpad_status()}
    assert rows["Utility assets"]["status"] == "fail"
    assert rows["Federation export"]["value"] == "Not built"
    assert list(tmp_path.iterdir()) == []  # a readiness check creates nothing

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "utility_assets.jsonl").write_text('{"a":1}\n{"a":2}\n\n')
    (tmp_path / "exports").mkdir()
    (tmp_path / "exports" / "hub_export.json").write_text("{}")
    rows = {row["label"]: row for row in config._launchpad_status()}
    assert rows["Utility assets"]["value"] == "2"
    assert rows["Federation export"]["status"] == "pass"


def test_status_falls_back_to_the_repository_data(monkeypatch):
    monkeypatch.delenv(config.DATA_ENV_VAR, raising=False)
    rows = {row["label"]: row for row in config._launchpad_status()}
    assert rows["Utility assets"]["status"] == "pass"
