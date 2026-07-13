"""Shared HTML shell for the desktop wrapper's status/splash/error pages.

Both the launcher (``launch.py``) and the same-origin ASGI app (``app_server.py``)
render tiny dark-theme pages while the real dashboard is starting or missing.
Keeping the base style here avoids two near-identical copies drifting apart.
"""

from __future__ import annotations

_FONT = "-apple-system,Segoe UI,Roboto,sans-serif"

BASE_CSS = (
    "html,body{height:100%;margin:0}"
    "body{display:flex;flex-direction:column;align-items:center;"
    f"justify-content:center;font-family:{_FONT};background:#0f172a;color:#e2e8f0;"
    "text-align:center;padding:0 32px}"
    "h1{font-size:18px;margin:0 0 12px}"
    "p{color:#94a3b8;font-size:14px;max-width:34rem}"
    "code{background:#1e293b;padding:2px 6px;border-radius:4px}"
)

SPINNER_CSS = (
    ".spin{width:34px;height:34px;border:4px solid #334155;border-top-color:#818cf8;"
    "border-radius:50%;animation:s .8s linear infinite;margin-bottom:18px}"
    "@keyframes s{to{transform:rotate(360deg)}}"
)


def render_page(body: str, *, title: str = "", extra_css: str = "") -> str:
    """Wrap ``body`` in the shared dark-theme HTML shell."""
    head_title = f"<title>{title}</title>" if title else ""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"{head_title}<style>{BASE_CSS}{extra_css}</style>"
        f"</head><body>{body}</body></html>"
    )
