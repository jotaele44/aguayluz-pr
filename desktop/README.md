# AguaYLuz desktop

## Install on macOS — no Terminal

1. Open this repository's **Releases** page and download the latest
   `PRII-AGUAYLUZ-macOS.dmg`.
2. Open the disk image and drag **AguaYLuz** to **Applications**.
3. Open AguaYLuz from Applications.

The release contains its own Python runtime, backend, compiled interface,
committed infrastructure data, and baseline outputs. Python, Node.js, Git,
Homebrew, and Terminal are not required.

On first launch, the native **Setup & Repair** screen asks for a writable data
location, copies baseline mutable outputs there without overwriting later work,
runs diagnostics, and starts the app. **Setup & Diagnostics** remains available
in the lower-right corner. The dashboard's export action runs in-process and
writes only to the selected application-data location.

Map basemap tiles and optional live/AI services may require an internet
connection; packaged data, tables, charts, and local exports remain available
without those optional integrations.

## If macOS blocks the first open

Open **System Settings → Privacy & Security**, find the message naming
AguaYLuz, and choose **Open Anyway**. No quarantine command is required.
Release CI applies an ad-hoc integrity signature, but public downloads are not
Apple-notarized unless a release is signed with project Developer ID
credentials.

The `PRII-AGUAYLUZ.app` committed in a source checkout is a Finder-only
download helper. The self-contained product is the app inside the release disk
image.

## Release contract

The `desktop-build` workflow builds on clean Linux, macOS, and Windows runners,
then tests both the fresh-machine setup contract and backend health on the
frozen executable. macOS CI verifies the bundle signature before producing the
`.dmg`.

`desktop/launch.py` and `desktop/config.py` are thin adapters over TheHub's
shared `prii_desktop` runtime. Source-checkout setup scripts remain developer
conveniences and are not part of end-user installation.
