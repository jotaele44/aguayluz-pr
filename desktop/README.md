# Run AguaYLuz as a desktop app

Double-click the launcher for your system in the repo root:

| System | File |
|---|---|
| macOS | `PRII-AGUAYLUZ.command` (or `PRII-AGUAYLUZ.app`) |
| Windows | `PRII-AGUAYLUZ.bat` |
| Linux | `PRII-AGUAYLUZ.sh` |

The **first run** needs an internet connection once: it creates a private
`.venv`, installs the Python dependencies, and builds the dashboard (requires
[Python 3.10+](https://www.python.org/downloads/) and
[Node.js](https://nodejs.org) to be installed). Every later run starts
instantly and **works offline** — the app serves the FastAPI backend and the
built dashboard from the same local port and opens a native window (or your
browser as a fallback).

On first launch, **Setup & Diagnostics** asks for a writable workspace and
copies the repo's bundled datasets and exports into it without ever
overwriting user-generated files. Reopen Setup & Diagnostics anytime from the
gear button in the app to change the workspace, run local checks, or repair
generated configuration — repair is idempotent and never deletes user data.

Offline caveat: map tiles and live refresh sources (USGS/EPA feeds) still need
a network connection; bundled data and dashboard views keep working offline.

## How it works

- `desktop/config.py` — the only per-repo file: app title/branding, the
  FastAPI import path (`server.backend.app:app`), the frontend directory
  (`dashboard/`), the requirement files installed into the private `.venv`,
  and the workspace data-home env var (`AGUAYLUZ_DATA_HOME`).
- `desktop/setup_actions.py` — the workspace-preparation action Setup &
  Diagnostics runs on first launch (copies bundled `data/`/`outputs/` into the
  chosen workspace without touching existing files).
- `desktop/app_server.py` / `desktop/launch.py` — thin per-repo shims around
  the shared `prii_desktop` package (from `thehub-pr/packages/prii_desktop`,
  consumed as a git-pinned dependency so the launcher runtime — same-origin
  serving, the native window, the per-user lock, Setup & Diagnostics — is
  written once for the whole federation).
- `desktop/setup.py` — idempotent one-time setup (stdlib only): creates the
  `.venv`, installs backend + desktop requirements (constrained by
  `constraints-desktop.txt` when present, for reproducible installs), and
  builds the Vite frontend. Re-run with `--force` to redo from scratch.

## Command line

```bash
python3 desktop/setup.py            # one-time setup
.venv/bin/python desktop/launch.py            # native window
.venv/bin/python desktop/launch.py --browser  # browser tab instead
.venv/bin/python desktop/launch.py --no-window  # server only
```

## macOS app icon

`PRII-AGUAYLUZ.app` is a double-click macOS app (Apple-silicon and Intel).
Double-click it in Finder and the dashboard opens in its own window — no
Terminal. The first launch runs the one-time setup (needs internet once, plus
Node.js for the dashboard build); after that it starts straight away and
works offline.

Because the app is a small self-locating wrapper around `desktop/launch.py`,
it must stay at the repo root (it finds the repo from its own location). If
macOS blocks the first open, see **If macOS blocks the first open** below.

## If macOS blocks the first open

The app is safe — it's an open-source launcher script you can read in
`Contents/MacOS/`. macOS blocks it only because it isn't signed with a paid
Apple Developer ID or notarized by Apple, so the first open may show *"cannot
be opened because Apple cannot check it for malicious software"* or an
*"unidentified developer"* notice. That's macOS quarantining files downloaded
from the internet (it happens especially with GitHub's **Download ZIP**). Any
one of the following clears it — you only do this once per download:

- **Easiest — run the helper.** Double-click **`Fix-Gatekeeper.command`** in
  the repo root, then open the app normally. If the helper is itself blocked,
  right-click it → **Open** to run it once.
- **Terminal (always works).** Paste this into Terminal (pasting a command is
  never blocked), then press Return:
  ```bash
  xattr -dr com.apple.quarantine "/path/to/aguayluz-pr/PRII-AGUAYLUZ.app"
  ```
  Tip: type `xattr -dr com.apple.quarantine ` (with a trailing space) and drag
  the app onto the Terminal window to fill in its path.
- **System Settings.** Double-click the app, let macOS block it, then open
  **System Settings → Privacy & Security**, scroll to the message naming the
  app, and click **Open Anyway**. On macOS Sequoia 15 and later this replaces
  the old right-click → **Open** trick.

If instead you see a dialog about the app running from a temporary read-only
copy ("App Translocation"), move the folder containing the app out of
Downloads/Trash (your home folder is fine), run `Fix-Gatekeeper.command`
again, and reopen the app.
