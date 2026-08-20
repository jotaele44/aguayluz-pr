#!/bin/sh
# Launcher (Linux/macOS). Double-click where your file manager allows executing
# scripts, or run ./PRII-AGUAYLUZ.sh. First run installs dependencies (needs
# internet once); later runs start the app directly and work offline.
set -eu
cd "$(dirname "$0")"

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$($candidate -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
    case "$version" in
      3.10|3.11|3.12)
        PYTHON_BIN="$candidate"
        break
        ;;
    esac
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.10+ is required. Install a supported interpreter and re-run this launcher."
  exit 1
fi

"$PYTHON_BIN" desktop/setup.py --ensure
exec .venv/bin/python desktop/launch.py "$@"
