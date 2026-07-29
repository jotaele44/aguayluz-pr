# AguaYLuz for macOS

Use the standalone macOS `.dmg` from a desktop release:

1. Open the downloaded `.dmg`.
2. Drag **AguaYLuz** to **Applications**.
3. Open AguaYLuz from Finder or Launchpad.
4. In **Setup & Diagnostics**, choose a workspace and select **Save & Open App**.

The release app is self-contained. End-user setup needs no Terminal and no
separate Python, Node.js, Git, package-manager, or source checkout.

First launch copies bundled datasets and exports into the selected writable
workspace. Existing user-generated files are never replaced. The installed app
remains read-only in Applications while monitoring data, exports, settings, and
logs live under the current macOS account.

Use the always-available gear button in the app to reopen **Setup & Diagnostics**.
It can choose the workspace, run local checks, or repair generated configuration.
Repair is idempotent and does not delete user data.

Map tiles and live refresh sources still require a network connection; bundled
data and dashboard views remain available offline.

## If macOS blocks the first open

Open **System Settings → Privacy & Security**, find the message naming AguaYLuz,
and select **Open Anyway**. This is the complete UI-only recovery path for an
unnotarized development release.

## Architecture

`desktop/config.py` is the thin AguaYLuz adapter. Native first-run setup,
repair, diagnostics, the per-user lock, same-origin serving, and the pywebview
window live in `thehub-pr/packages/prii_desktop`. Release CI builds and smokes
the frozen app on macOS, Windows, and Linux and packages the macOS `.dmg`.

`desktop/setup.py` and command-line launcher flags remain developer conveniences;
they are not part of end-user installation.
