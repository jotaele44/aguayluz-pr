"""One-time setup for the desktop wrapper (stdlib only).

Creates a private .venv, installs the backend + desktop requirements, and
builds the frontend for same-origin serving (empty VITE_API_BASE). Idempotent:
re-runs are skipped via a marker file unless --force is given.

Usage:
  python desktop/setup.py            run setup (skips when already complete)
  python desktop/setup.py --ensure   quiet fast-path used by the launchers
  python desktop/setup.py --force    redo setup from scratch
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop import config  # noqa: E402
from desktop.config import DIST_DIR, FRONTEND_DIR, REPO_ROOT, REQUIREMENT_FILES  # noqa: E402

VENV_DIR = REPO_ROOT / ".venv"
MARKER = Path(__file__).resolve().parent / ".setup-complete"
MIN_PYTHON = (3, 10)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def is_complete() -> bool:
    return MARKER.exists() and venv_python().exists() and (DIST_DIR / "index.html").exists()


def supported_python_candidates() -> list[str]:
    return ["python3.12", "python3.11", "python3.10", "python3", "python"]


def resolve_python_executable() -> str:
    for candidate in supported_python_candidates():
        executable = shutil.which(candidate)
        if not executable:
            continue
        try:
            version = subprocess.check_output(
                [executable, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            continue
        if version.startswith("3."):
            major, minor = map(int, version.split(".")[:2])
            if major == 3 and minor in (10, 11, 12):
                return executable
    raise SystemExit(
        "A supported Python 3.10–3.12 interpreter is required. "
        "Install Python 3.12 or 3.11 and re-run the launcher."
    )


def setup_python() -> None:
    python_executable = resolve_python_executable()
    if venv_python().exists():
        try:
            venv_version = subprocess.check_output(
                [str(venv_python()), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if not venv_version.startswith("3.10") and not venv_version.startswith("3.11") and not venv_version.startswith("3.12"):
                print(f"Resetting incompatible virtual environment ({venv_version}) …")
                shutil.rmtree(VENV_DIR)
        except Exception:
            pass
    if not venv_python().exists():
        print(f"Creating virtual environment at {VENV_DIR} using {python_executable} …")
        subprocess.run([python_executable, "-m", "venv", str(VENV_DIR)], check=True)
    pip = [str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "--quiet"]
    run(pip)
    install = [str(venv_python()), "-m", "pip", "install", "--quiet"]
    for req in REQUIREMENT_FILES:
        install += ["-r", str(req)]
    run(install)
    extra = list(getattr(config, "EXTRA_PIP_SPECS", []))
    if extra:
        run([str(venv_python()), "-m", "pip", "install", "--quiet", *extra])


def setup_frontend() -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit(
            "npm not found. Install Node.js (https://nodejs.org) and re-run python desktop/setup.py"
        )
    env = dict(os.environ)
    env["VITE_API_BASE"] = ""
    env.update(getattr(config, "EXTRA_BUILD_ENV", {}))
    if (FRONTEND_DIR / "package-lock.json").exists():
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND_DIR, env=env)
    else:
        run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND_DIR, env=env)
    run([npm, "run", "build"], cwd=FRONTEND_DIR, env=env)
    if not (DIST_DIR / "index.html").exists():
        raise SystemExit(f"Frontend build did not produce {DIST_DIR / 'index.html'}")


def main() -> None:
    args = set(sys.argv[1:])
    if "--force" in args:
        MARKER.unlink(missing_ok=True)
    if is_complete():
        if "--ensure" not in args:
            print("Setup already complete (use --force to redo).")
        return
    setup_python()
    setup_frontend()
    MARKER.write_text("ok\n", encoding="utf-8")
    print("Desktop setup complete.")


if __name__ == "__main__":
    main()
