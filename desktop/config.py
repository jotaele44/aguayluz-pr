"""Desktop-wrapper configuration for this repo.

The desktop/ folder is a shared PRII federation template; only this file
differs between repos.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Window title of the desktop app.
APP_TITLE = "AguaYLuz"
APP_ID = "AguaYLuz"
BRAND_ACCENT = "#0de3d8"
BRAND_ACCENT_STRONG = "#087d77"
ICON_PATH = REPO_ROOT / "assets" / "branding" / "icon-256.png"
SETUP_VERSION = 1
DATA_ENV_VAR = "AGUAYLUZ_DATA_HOME"
SETUP_ACTION = "desktop.setup_actions:prepare_workspace"

# Dotted import path of the FastAPI application object.  app.py imports the
# established backend and replaces only /readings with the metric-safe contract.
APP_IMPORT = "server.backend.app:app"

# Directory containing the Vite frontend (with package.json).
FRONTEND_DIR = REPO_ROOT / "dashboard"

# Vite build output served by the desktop app.
DIST_DIR = FRONTEND_DIR / "dist"

# Requirement files installed into the private .venv by desktop/setup.py.
REQUIREMENT_FILES = [
    REPO_ROOT / "server" / "backend" / "requirements.txt",
    REPO_ROOT / "requirements-desktop.txt",
]

# Health endpoint used to detect that the backend is up.
HEALTH_PATH = "/health"


def _launchpad_status() -> list[dict[str, str]]:
    """Readiness rows for the Launch Pad. Runs before the backend exists, so it
    counts the files the backend will load (server/backend/main.py DATA/OUTPUTS).
    """
    workspace = os.environ.get(DATA_ENV_VAR, "").strip()
    data = Path(workspace) / "data" if workspace else REPO_ROOT / "data"
    exports = Path(workspace) / "exports" if workspace else REPO_ROOT / "outputs"

    def lines(name: str) -> int:
        path = data / name
        if not path.is_file():
            return 0
        with path.open("rb") as stream:
            return sum(1 for line in stream if line.strip())

    assets, alerts = lines("utility_assets.jsonl"), lines("alert_events.jsonl")
    has_export = (exports / "hub_export.json").is_file()
    return [
        {
            "label": "Utility assets",
            "value": f"{assets:,}" if assets else "Missing",
            "status": "pass" if assets else "fail",
            "detail": (
                f"Asset inventory loaded from {data}."
                if assets
                else f"utility_assets.jsonl was not found in {data}. Open Setup & "
                "Diagnostics and choose Repair to copy the bundled datasets."
            ),
        },
        {
            "label": "Alert events",
            "value": f"{alerts:,}",
            "status": "pass" if alerts else "info",
            "detail": "Recorded alert events available to the Alerts and Monitoring pages.",
        },
        {
            "label": "Federation export",
            "value": "Present" if has_export else "Not built",
            "status": "pass" if has_export else "info",
            "detail": (
                "hub_export.json is available; Overview shows coverage and readiness."
                if has_export
                else "No hub_export.json yet, so Overview shows no readiness summary. "
                "An Operator can build it from System & Tools."
            ),
        },
    ]


# Pre-launch screen shown by the shared runtime (prii_desktop.launchpad).
#
# Operator sets no credential: with API_SECRET_KEY unset the API is open to this
# computer, which is how the desktop app has always run. Guest adds a refusal in
# front of every non-GET route, including the /water-disruption POSTs that the
# API key never covered.
LAUNCHPAD = {
    "tagline": "Water, power and utility monitoring for Puerto Rico",
    "summary": (
        "AguaYLuz is the federation's water, wastewater, power and outage "
        "monitoring producer. This diagnostic dashboard shows utility assets, "
        "alerts and outages, hydrology and regulatory records, and the review "
        "queues behind what the producer exports to TheHub."
    ),
    "highlights": [
        "Alerts and outages",
        "Asset map",
        "Hydromet and aquifers",
        "Regulatory review",
        "Source intelligence",
    ],
    "status": _launchpad_status,
    # NAV_GROUPS in dashboard/src/components/layout/Sidebar.jsx.
    "start_pages": [
        {"route": "/", "label": "Overview",
         "description": "Counts, coverage and current alert posture."},
        {"route": "/map", "label": "Map"},
        {"route": "/alerts", "label": "Alerts"},
        {"route": "/outages", "label": "Outages"},
        {"route": "/monitoring", "label": "Monitoring",
         "description": "Monitoring incidents and their operator timeline."},
        {"route": "/assets", "label": "Assets"},
        {"route": "/water-disruption", "label": "Water & Weather"},
        {"route": "/hydromet", "label": "NWS Hydromet"},
        {"route": "/aquifer-bands", "label": "Aquifer Bands"},
        {"route": "/water-use", "label": "Water Use"},
        {"route": "/hydro-inventory", "label": "Hydro Inventory"},
        {"route": "/environmental-exposure", "label": "Environment"},
        {"route": "/cave-karst", "label": "Cave & Karst"},
        {"route": "/regulatory", "label": "Regulatory"},
        {"route": "/regulatory/review", "label": "Regulatory Review"},
        {"route": "/review", "label": "Review Queue"},
        {"route": "/analytics", "label": "Analytics"},
        {"route": "/source-intelligence", "label": "Source Intelligence"},
        {"route": "/logs", "label": "Live Logs"},
        {"route": "/system", "label": "System & Tools",
         "description": "Status, exports, notifications and the API key."},
    ],
    "guest": {
        "label": "Guest",
        "description": (
            "Read-only. Browse every page. Review decisions, edits, incident "
            "transitions, data refreshes, exports, notifications and AI queries "
            "are refused."
        ),
    },
    "operator": {
        "label": "Operator",
        "description": (
            "Full access from this computer: record review decisions, manage "
            "incidents, refresh hydromet sources, run exports and send "
            "notifications."
        ),
    },
    # None of the API's POST or PATCH routes is a pure read.
    "guest_guard": {"allow": []},
    "options": [
        {
            "id": "anthropic_api_key",
            "label": "Anthropic API key",
            "kind": "secret",
            "env": "ANTHROPIC_API_KEY",
            "operator_only": True,
            "help": (
                "Optional. Enables the AI query box, which sends your question "
                "and matching records to the Anthropic API and is billed to "
                "this key."
            ),
        },
        {
            "id": "slack_webhook_url",
            "label": "Slack webhook URL",
            "kind": "secret",
            "env": "SLACK_WEBHOOK_URL",
            "operator_only": True,
            "help": "Optional. Lets Notify post alert summaries to a Slack channel.",
        },
        {
            "id": "ntfy_topic",
            "label": "ntfy push topic",
            "kind": "text",
            "env": "NTFY_TOPIC",
            "operator_only": True,
            "pattern": "[A-Za-z0-9_-]{0,64}",
            "placeholder": "for example aguayluz-pr-alerts",
            "help": (
                "Optional. Lets Notify send push messages through ntfy.sh. "
                "Anyone who knows the topic name can read them."
            ),
        },
    ],
}
