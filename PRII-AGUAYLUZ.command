#!/bin/bash
# Double-click launcher (macOS). First run installs dependencies (needs
# internet once); later runs start the app directly and work offline.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
    case "$version" in
      3.10|3.11|3.12)
        PYTHON_BIN="$candidate"
        break
        ;;
    esac
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.10-3.12 is required. Install a supported interpreter and re-run this launcher."
  [ -t 0 ] && read -r -p "Press Enter to close…"
  exit 1
fi

LOG="$(mktemp "${TMPDIR:-/tmp}/prii-aguayluz-pr-setup.XXXXXX")"
if ! "$PYTHON_BIN" desktop/setup.py --ensure >"$LOG" 2>&1; then
  cat "$LOG"
  echo
  echo "Setup failed. If Node.js is missing, install it from https://nodejs.org and re-run this launcher."
  echo "Full log: $LOG"
  [ -t 0 ] && read -r -p "Press Enter to close…"
  exit 1
fi
exec .venv/bin/python desktop/launch.py "$@"
