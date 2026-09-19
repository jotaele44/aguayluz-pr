#!/usr/bin/env python3
"""Index PREB docket NEPR-MI-2019-0007 as an independent reliability source family.

The docket page advertises a published-document denominator. This producer fails closed
unless the parsed document-row count equals that advertised count. It preserves RAW
title, subject, displayed date, order date, and document URL; classification is discovery
metadata only and never makes PREB monthly/quarterly reliability reports equivalent to
MiLUMA live outage observations.

Output is runtime/public-source metadata, not downloaded document payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DOCKET_ID = "NEPR-MI-2019-0007"
DEFAULT_URL = "https://energia.pr.gov/numero_orden/nepr-mi-2019-0007/"
DEFAULT_OUT = "data/preb_reliability_docket.jsonl"
UA = "Mozilla/5.0 (compatible; AguaYLuz-PR/1.0; public-docket-indexer)"


class DocketParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_tr = False
        self._in_td = False
        self._current_cell: list[str] = []
        self._cells: list[str] = []
        self._links: list[tuple[str, str]] = []
        self._row_links: list[tuple[str, str]] = []
        self.rows: list[dict[str, Any]] = []
        self.page_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "tr":
            self._in_tr = True
            self._cells = []
            self._row_links = []
        elif tag == "td" and self._in_tr:
            self._in_td = True
            self._current_cell = []
        elif tag == "a" and self._in_tr:
            href = attrs_d.get("href")
            if href:
                self._links.append((href, ""))

    def handle_data(self, data: str) -> None:
        text = data
        self.page_text.append(text)
        if self._in_td:
            self._current_cell.append(text)
        if self._links:
            href, label = self._links[-1]
            self._links[-1] = (href, label + text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_tr and self._links:
            href, label = self._links.pop()
            self._row_links.append((href, " ".join(label.split())))
        elif tag == "td" and self._in_tr and self._in_td:
            self._cells.append(" ".join("".join(self._current_cell).split()))
            self._current_cell = []
            self._in_td = False
        elif tag == "tr" and self._in_tr:
            self._finish_row()
            self._in_tr = False
            self._cells = []
            self._row_links = []

    def _finish_row(self) -> None:
        if len(self._cells) < 3 or not self._row_links:
            return
        doc_links = [
            (href, label)
            for href, label in self._row_links
            if href.lower().startswith(("http://", "https://"))
        ]
        if not doc_links:
            return
        self.rows.append(
            {
                "cells": list(self._cells),
                "links": doc_links,
            }
        )


def _advertised_count(text: str) -> int:
    m = re.search(
        r"(?:Documentos\s+Publicados|Available\s+files)\s*:\s*([0-9][0-9,]*)",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        raise ValueError("PREB docket advertised document count not found")
    return int(m.group(1).replace(",", ""))


def _split_title_subject(raw_first_cell: str) -> tuple[str, str]:
    marker = re.search(r"\b(?:Asunto|Subject)\s*:\s*", raw_first_cell, re.IGNORECASE)
    if not marker:
        return raw_first_cell, ""
    return (
        raw_first_cell[: marker.start()].strip(),
        raw_first_cell[marker.end() :].strip(),
    )


def discovery_class(title: str, subject: str) -> str:
    text = f"{title} {subject}".casefold()
    if "saidi_saifi_outage_data" in text or "outage data" in text:
        return "RAW_RELIABILITY_DATA_CANDIDATE"
    if "monthly report" in text and "reliability" in text:
        return "MONTHLY_RELIABILITY_REPORT"
    if "performance metrics" in text or "quarterly report" in text:
        return "PERFORMANCE_METRICS_REPORT"
    if "resolution and order" in text or title.casefold().startswith("resolution"):
        return "REGULATORY_ORDER"
    return "OTHER_DOCKET_DOCUMENT"


def _manifestation_id(doc_url: str, title: str, subject: str, order_date: str) -> str:
    raw = "\x1f".join((doc_url, title, subject, order_date)).encode("utf-8")
    return f"PREB_{DOCKET_ID}_{hashlib.sha256(raw).hexdigest()[:20]}"


def parse_docket(html_text: str, source_url: str, retrieval_ts: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parser = DocketParser()
    parser.feed(html_text)
    advertised = _advertised_count(" ".join(parser.page_text))

    rows: list[dict[str, Any]] = []
    for index, parsed in enumerate(parser.rows, start=1):
        cells = parsed["cells"]
        raw_first = cells[0]
        title, subject = _split_title_subject(raw_first)
        displayed_date = cells[1] if len(cells) > 1 else ""
        order_date = cells[2] if len(cells) > 2 else ""
        href, _label = parsed["links"][0]
        doc_url = urllib.parse.urljoin(source_url, href)
        rows.append(
            {
                "manifestation_id": _manifestation_id(doc_url, title, subject, order_date),
                "docket_id": DOCKET_ID,
                "source_row_index": index,
                "title_raw": title,
                "subject_raw": subject,
                "displayed_date_raw": displayed_date,
                "order_date_raw": order_date,
                "document_url": doc_url,
                "discovery_class": discovery_class(title, subject),
                "comparability_to_miluma_live": "NONCOMPARABLE_BY_DEFAULT",
                "retrieval_ts": retrieval_ts,
                "source_url": source_url,
            }
        )

    if len(rows) != advertised:
        raise ValueError(
            f"PREB docket denominator mismatch: advertised={advertised} parsed={len(rows)}"
        )

    urls = [row["document_url"] for row in rows]
    summary = {
        "docket_id": DOCKET_ID,
        "source_url": source_url,
        "retrieval_ts": retrieval_ts,
        "advertised_document_count": advertised,
        "parsed_document_count": len(rows),
        "duplicate_document_url_count": len(urls) - len(set(urls)),
        "classification_counts": {
            key: sum(1 for row in rows if row["discovery_class"] == key)
            for key in sorted({row["discovery_class"] for row in rows})
        },
        "certification_state": "PASS" if len(rows) == advertised else "FAIL",
    }
    return rows, summary


def fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"PREB docket fetch/decode failed: {exc}") from exc


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--summary-out", default="data/preb_reliability_docket_summary.json")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    retrieval_ts = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    rows, summary = parse_docket(fetch(args.url, args.timeout), args.url, retrieval_ts)
    write_jsonl(Path(args.out), rows)
    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"docket={DOCKET_ID} advertised={summary['advertised_document_count']} "
        f"parsed={summary['parsed_document_count']} duplicates="
        f"{summary['duplicate_document_url_count']} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
