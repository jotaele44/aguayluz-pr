# PyInstaller spec for the standalone desktop build (Phase 2).
# Build (on the target OS):
#   pip install pyinstaller
#   pyinstaller desktop/pyinstaller.spec --distpath dist-desktop
# Produces a self-contained one-folder app: dist-desktop/PRII-AGUAYLUZ/
# The bundle mirrors the repo layout so server/backend/main.py finds data/
# and releases/ with its normal relative paths.

import os
import sys
from pathlib import Path

REPO_ROOT = Path(SPECPATH).resolve().parent
APP_NAME = "PRII-AGUAYLUZ"

# Branding is generated from assets/branding/icon.png by
# thehub-pr/tools/build_program_icons.py, so the frozen build, the committed
# PRII-*.app bundle and the web favicons all trace back to one master.
BRANDING = REPO_ROOT / "assets" / "branding"
# PyInstaller wants .ico on Windows and .icns on macOS; it warns and ignores the
# argument on other platforms, so leave it unset there.
EXE_ICON = str(BRANDING / "icon.ico") if sys.platform == "win32" else None

# Windowed by default (no console window for double-click users). CI sets
# PRII_CONSOLE=1 to build a console binary it can smoke-test with visible stdio.
CONSOLE = os.environ.get("PRII_CONSOLE") == "1"

datas = [
    (str(REPO_ROOT / "dashboard" / "dist"), "dashboard/dist"),
    (str(REPO_ROOT / "data"), "data"),
    (str(REPO_ROOT / "scripts"), "scripts"),
    (str(REPO_ROOT / "src"), "src"),
    (str(REPO_ROOT / "schemas"), "schemas"),
    (str(REPO_ROOT / "config"), "config"),
    (str(BRANDING / "icon-256.png"), "assets/branding"),
]
if (REPO_ROOT / "outputs").exists():
    datas.append((str(REPO_ROOT / "outputs"), "outputs"))

a = Analysis(
    [str(REPO_ROOT / "desktop" / "launch.py")],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "src")],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "desktop.app_server",
        "server.backend.app",
        "server.backend.main",
        # src-layout application package reached transitively from
        # server.backend.cave_karst_api in the frozen backend.
        "aguayluz.cave_karst",
        # Shared desktop-wrapper runtime (thehub-pr/packages/prii_desktop),
        # imported by the desktop/ shims — bundle it into the frozen build.
        "prii_desktop",
        "prii_desktop.launcher",
        "prii_desktop.appserver",
        "prii_desktop.config",
        "prii_desktop.setup_center",
        "desktop.setup_actions",
        # Loaded by the in-app federation export action from bundled source.
        "prii_export_utils",
        "jsonschema",
        "yaml",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_NAME,
    console=CONSOLE,
    icon=EXE_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(BRANDING / "AppIcon.icns"),
        bundle_identifier="pr.prii.aguayluz",
        info_plist={
            "CFBundleDisplayName": "AguaYLuz",
            "CFBundleName": "AguaYLuz",
        },
    )
