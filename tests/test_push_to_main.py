"""Tests for scripts/push_to_main.sh against throwaway git repos (offline).

`gh` and the docs-sync checker are replaced by stubs on PATH that record their
arguments, so each case can assert what reached main and which status was set.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "push_to_main.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, path: str, text: str, message: str) -> str:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    for key, value in (("user.name", "t"), ("user.email", "t@example.com")):
        _git(seed, "config", key, value)
    _commit(seed, "README.md", "readme\n", "init")
    _git(seed, "push", "-q", "origin", "HEAD:main")

    job = tmp_path / "job"
    _git(tmp_path, "clone", "-q", str(origin), str(job))
    for key, value in (("user.name", "bot"), ("user.email", "bot@example.com")):
        _git(job, "config", key, value)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_log = tmp_path / "gh.log"
    (bin_dir / "gh").write_text(f'#!/bin/sh\necho "$*" >> {gh_log}\n', encoding="utf-8")
    check = bin_dir / "check"
    check.write_text('#!/bin/sh\nexit "${CHECK_EXIT:-0}"\n', encoding="utf-8")
    for exe in (bin_dir / "gh", check):
        exe.chmod(0o755)

    run_env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_SHA": _git(job, "rev-parse", "HEAD"),
        "GITHUB_REF_NAME": "main",
        "GITHUB_REPOSITORY": "jotaele44/aguayluz-pr",
        "GITHUB_RUN_ID": "42",
        "GITHUB_WORKFLOW": "Test monitor",
        "DOCS_SYNC_CMD": str(check),
    }
    return {"origin": origin, "seed": seed, "job": job, "gh_log": gh_log, "env": run_env}


def _run(env: dict, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_SCRIPT), "test"],
        cwd=env["job"],
        env={**env["env"], **extra},
        capture_output=True,
        text=True,
    )


def _origin_main(env: dict) -> str:
    return _git(env["origin"], "rev-parse", "main")


def _status_calls(env: dict) -> list[str]:
    log = env["gh_log"]
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _branches(env: dict) -> str:
    return _git(env["origin"], "branch", "--list")


def test_nothing_committed_is_a_no_op(env):
    before = _origin_main(env)
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "Nothing new to push" in result.stdout
    assert _origin_main(env) == before
    assert _status_calls(env) == []


def test_data_commit_reaches_main_with_a_success_status(env):
    _commit(env["job"], "data/state.json", "{}\n", "data: refresh")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    pushed = _origin_main(env)
    assert _git(env["origin"], "show", f"{pushed}:data/state.json") == "{}"
    [call] = _status_calls(env)
    assert f"repos/jotaele44/aguayluz-pr/statuses/{pushed}" in call
    assert "state=success" in call and "context=docs-sync" in call
    assert "actions/runs/42" in call
    assert "bot/test" not in _branches(env)


def test_main_moved_meanwhile_replays_the_commit_on_the_new_tip(env):
    _commit(env["job"], "data/state.json", "{}\n", "data: refresh")
    other = _commit(env["seed"], "notes.md", "elsewhere\n", "unrelated change")
    _git(env["seed"], "push", "-q", "origin", "HEAD:main")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    pushed = _origin_main(env)
    assert _git(env["origin"], "rev-parse", f"{pushed}^") == other
    assert _git(env["origin"], "show", f"{pushed}:data/state.json") == "{}"
    [call] = _status_calls(env)
    assert f"statuses/{pushed}" in call


def test_failing_check_is_recorded_and_nothing_is_pushed(env):
    before = _origin_main(env)
    _commit(env["job"], "data/state.json", "{}\n", "data: refresh")
    result = _run(env, CHECK_EXIT="1")
    assert result.returncode == 1
    assert _origin_main(env) == before
    [call] = _status_calls(env)
    assert "state=failure" in call
    assert "bot/test" not in _branches(env)


def test_conflicting_data_commit_fails_without_pushing(env):
    _commit(env["seed"], "data/state.json", "theirs\n", "data: other run")
    _git(env["seed"], "push", "-q", "origin", "HEAD:main")
    before = _origin_main(env)
    _commit(env["job"], "data/state.json", "ours\n", "data: refresh")
    result = _run(env)
    assert result.returncode == 1
    assert "conflicts" in result.stderr
    assert _origin_main(env) == before
    assert _status_calls(env) == []


def test_data_already_on_main_is_not_pushed_again(env):
    _commit(env["seed"], "data/state.json", "{}\n", "data: same refresh, other run")
    _git(env["seed"], "push", "-q", "origin", "HEAD:main")
    before = _origin_main(env)
    _commit(env["job"], "data/state.json", "{}\n", "data: refresh")
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "already has this data" in result.stdout
    assert _origin_main(env) == before
    assert _status_calls(env) == []
