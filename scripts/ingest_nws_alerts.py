#!/usr/bin/env python3
"""Ingest NOAA/NWS active alerts for Puerto Rico into service_events.jsonl.

Fetches current NWS alerts (flood watches, hurricane warnings, tropical storm
advisories, storm surge) for PR from the public api.weather.gov endpoint. Alerts
that affect water infrastructure (floods, tropical systems, storm surge) become
service_event rows at evidence_tier=T1. Idempotent by NWS alert ID.

Raw weather events use the existing unknown enum; the weather promoter emits
hazard alerts. A warning is not evidence of contamination or service loss.

Only "Actual" status alerts are ingested (Test/Exercise/Draft are skipped).

Source: https://api.weather.gov/alerts/active?area=PR  (no auth required)

Merges idempotently: existing NWS rows (matched by source_ref prefix) are
replaced; all other events are preserved.

Run:
    python scripts/ingest_nws_alerts.py          # live fetch
    python scripts/ingest_nws_alerts.py --src alerts.json  # offline
    python scripts/ingest_nws_alerts.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NWS_URL = "https://api.weather.gov/alerts/active?area=PR"
REPO = Path(__file__).resolve().parent.parent
SOURCE_PREFIX = "NWS-IDP"
SLUG_RE = re.compile(r"[^A-Za-z0-9_-]")

# NWS event name keywords → service_event event_type
_FLOOD_KEYWORDS = frozenset(["flood", "flash flood", "coastal flood", "urban"])
_SURGE_KEYWORDS = frozenset(["storm surge"])
_TROPICAL_KEYWORDS = frozenset(["hurricane", "tropical storm", "tropical depression", "typhoon"])


def _event_type(nws_event: str) -> str:
    # The shared service-event enum has no hazard member. A warning alone
    # establishes neither contamination nor a utility interruption.
    return "unknown"


def _slug(text: str, maxlen: int = 40) -> str:
    return SLUG_RE.sub("-", str(text).strip())[:maxlen].strip("-")


def _isodate(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s or s.lower() in ("", "null", "none"):
        return None
    return s if ("T" in s) else (s + "T00:00:00Z")


def _fetch_live() -> tuple[dict[str, Any], bytes]:
    sys.path.insert(0, str(REPO / "src"))
    from aguayluz.http_retry import get_with_retry

    r = get_with_retry(
        NWS_URL,
        headers={"User-Agent": "aguayluz-pr/0.1 (github.com/jotaele44/aguayluz-pr)"},
        timeout=60,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.json(), r.content


def build_events(doc: dict[str, Any]) -> list[dict]:
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
        raise ValueError("NWS snapshot must contain a features array")
    if (doc.get("pagination") or {}).get("next"):
        raise ValueError("Paginated NWS snapshot is incomplete; cannot retire alerts")
    features = doc["features"]
    rows: list[dict] = []
    for feat in features:
        if not isinstance(feat, dict) or not isinstance(feat.get("properties"), dict):
            raise ValueError("Malformed NWS feature; snapshot rejected")
        props = feat.get("properties") or {}
        if props.get("status") not in {"Actual", "Test", "Exercise", "System", "Draft"}:
            raise ValueError("Missing or invalid NWS status; snapshot rejected")
        if (props.get("status") or "").strip() != "Actual":
            continue
        alert_id = props.get("id")
        if not isinstance(alert_id, str) or not alert_id.strip():
            raise ValueError("Actual NWS alert lacks source identity")
        nws_event = (props.get("event") or "").strip()
        effective = _isodate(props.get("effective") or props.get("onset"))
        if not effective:
            raise ValueError("Actual NWS alert lacks effective time")
        parsed = datetime.fromisoformat(effective.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("NWS effective time lacks timezone")
        day = effective[:10].replace("-", "")
        if len(day) != 8:
            continue
        # Full source ID digest; numeric suffixes are not unique source identity.
        id_slug = hashlib.sha256(alert_id.encode("utf-8")).hexdigest()
        event_id = f"AYL_EVT_{day}_NWS-{id_slug}"
        # Affected area: use areaDesc or fallback
        area_desc = (props.get("areaDesc") or "Puerto Rico").strip()
        severity = (props.get("severity") or "").strip()
        expires = _isodate(props.get("ends") or props.get("expires"))
        if expires:
            end = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if end.tzinfo is None or end < parsed:
                raise ValueError("Invalid NWS expiration time")
        rows.append({
            "event_id": event_id,
            "event_type": _event_type(nws_event),
            "affected_area": area_desc,
            "municipality": None,
            "zone": None,
            "status_text": (
                f"event={nws_event!r} severity={severity} "
                f"sender={props.get('senderName', 'NWS')!r}"
                + (" lifecycle=closed" if props.get("messageType") == "Cancel" else "")
            ),
            "start_time": effective,
            "end_time": expires,
            "reported_customers_or_users": None,
            "source_ref": alert_id or NWS_URL,
            "source_hash": hashlib.sha256(json.dumps(feat, ensure_ascii=False, sort_keys=True,
                                                      separators=(",", ":")).encode("utf-8")).hexdigest(),
            "evidence_tier": "T1",
            "confidence": 85,
            "review_status": "accepted",
            "linked_asset_ids": [],
        })
    return rows


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge(existing: list[dict], nws: list[dict], *, observed_at: str | None = None) -> list[dict]:
    """Reconcile one validated complete snapshot; retain withdrawn history.

    Raw payload snapshots preserve the superseded bytes. Legacy generated IDs
    identify rows owned by this producer; an arbitrary urn alone never does.
    """
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    by_id: dict[str, dict] = {}
    current_sources = {e["source_ref"]: e["event_id"] for e in nws}
    for old in existing:
        row = dict(old)
        owned = bool(re.fullmatch(r"AYL_EVT_\d{8}_NWS-[A-Za-z0-9_-]+", str(row.get("event_id", ""))))
        if owned:
            row["event_type"] = "unknown"
            if current_sources.get(row.get("source_ref")) != row["event_id"]:
                if " lifecycle=closed" not in str(row.get("status_text") or ""):
                    row["status_text"] = str(row.get("status_text") or "") + " lifecycle=closed"
                if not row.get("end_time"):
                    row["end_time"] = observed_at
        key = row["event_id"]
        if key in by_id and by_id[key] != row:
            raise ValueError("Conflicting existing event IDs; reconciliation rejected")
        by_id[key] = row
    for e in nws:
        prior = by_id.get(e["event_id"])
        if prior and prior.get("source_ref") != e["source_ref"]:
            raise ValueError("NWS identity collision; reconciliation rejected")
        by_id[e["event_id"]] = e
    if len(current_sources) != len(nws):
        raise ValueError("Duplicate source identities in NWS snapshot")
    if len({e["event_id"] for e in nws}) != len(nws):
        raise ValueError("Duplicate generated NWS identities")
    return sorted(by_id.values(), key=lambda row: row["event_id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=None,
                    help="Offline: path to a pre-downloaded NWS alerts JSON file.")
    ap.add_argument("--out", default="data/service_events.jsonl")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print records without writing.")
    args = ap.parse_args()

    if args.src:
        raw = Path(args.src).read_bytes()
        doc = json.loads(raw)
        origin = str(args.src)
    else:
        try:
            doc, raw = _fetch_live()
            origin = NWS_URL
        except Exception as e:  # noqa: BLE001
            print(f"live fetch failed ({e}); pass --src <alerts.json>", file=sys.stderr)
            return 1

    events = build_events(doc)

    if args.dry_run:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        print(f"(dry-run) {len(events)} NWS alert(s) from {origin}")
        return 0

    out = Path(args.out)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    combined = merge(_read_jsonl(out), events, observed_at=retrieved_at)
    # Freeze exact acquisition bytes and the pre-reconciliation event ledger.
    archive = out.parent / "nws_snapshots"
    archive.mkdir(parents=True, exist_ok=True)
    for label, payload in (("source", raw), ("previous_events", out.read_bytes() if out.exists() else b"")):
        digest = hashlib.sha256(payload).hexdigest()
        frozen = archive / f"{label}_{digest}.json"
        if frozen.exists() and frozen.read_bytes() != payload:
            raise ValueError("Frozen NWS archive does not match its content hash")
        if not frozen.exists():
            frozen.write_bytes(payload)
    receipt = {
        "source_url": NWS_URL,
        "origin": origin,
        "retrieval_utc": retrieved_at,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_hash_identity": "BYTE",
        "row_source_hash_identity": "LOGICAL_CANONICAL_FEATURE_JSON",
        "feature_count": len(doc["features"]),
        "retained_count": len(events),
        "excluded_non_actual_count": len(doc["features"]) - len(events),
        "snapshot_scope": "PR_ACTIVE_ALERTS",
        "complete_response_validated": True,
        "live_certification": "OPEN",
    }
    receipt_id = retrieved_at.replace(":", "").replace("+", "_")
    (archive / f"receipt_{hashlib.sha256(raw).hexdigest()}_{receipt_id}.json").write_text(json.dumps(receipt, indent=2) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(r) + "\n" for r in combined))
    temporary.replace(out)
    print(f"source: {origin}")
    print(f"wrote {len(events)} NWS alert(s) -> {out}")
    print(f"  total events in file: {len(combined)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
