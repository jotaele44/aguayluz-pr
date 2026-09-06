from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

Disposition = Literal[
    "DISCOVERED", "RETRIEVED", "EXCLUDED", "UNAVAILABLE", "UNRESOLVED"
]

_USACE_HOST_REWRITES = {
    "saj.usace.afpims.mil": "www.saj.usace.army.mil",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def discovery_key(value: str) -> str:
    """Normalization for discovery only. Never use as an identity proof."""
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).strip()


def canonicalize_usace_url(raw_url: str, *, base_url: str | None = None) -> str:
    value = urljoin(base_url or "", raw_url.strip())
    split = urlsplit(value)
    host = _USACE_HOST_REWRITES.get(split.netloc.casefold(), split.netloc)
    return urlunsplit((split.scheme.lower(), host, split.path, split.query, ""))


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    source_type: str
    url: str
    authority: str
    scope: str
    enabled: bool = True
    adapter: str | None = None


@dataclass(frozen=True)
class DiscoveryCandidate:
    source_id: str
    source_page: str
    project_raw: str
    document_raw: str
    url_raw: str
    url_canonical: str
    discovered_utc: str
    discovery_method: str
    disposition: Disposition = "DISCOVERED"
    disposition_reason: str | None = None

    @property
    def project_discovery_key(self) -> str:
        return discovery_key(self.project_raw)

    @property
    def document_discovery_key(self) -> str:
        return discovery_key(self.document_raw)


@dataclass(frozen=True)
class RetrievalReceipt:
    source_id: str
    url: str
    retrieved_utc: str
    status_code: int
    content_type: str | None
    byte_count: int
    sha256: str
    final_url: str
    output_path: str


class _TableParser(HTMLParser):
    """Small dependency-free table parser for DNN/USACE index pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attrs_map = {k.casefold(): v for k, v in attrs}
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": [], "links": []}
        elif tag == "a" and self._cell is not None:
            self._anchor_href = attrs_map.get("href")
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
        if self._anchor_href is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "a" and self._cell is not None and self._anchor_href is not None:
            text = " ".join("".join(self._anchor_text).split())
            self._cell["links"].append((text, self._anchor_href))
            self._anchor_href = None
            self._anchor_text = []
        elif tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._cell["text"] = " ".join("".join(self._cell["text"]).split())
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _row_text(row: list[dict[str, Any]]) -> str:
    return " | ".join(str(cell.get("text", "")) for cell in row)


def discover_saj_environmental_documents(
    html: str,
    *,
    source_id: str,
    source_page: str,
    retrieved_utc: str | None = None,
) -> list[DiscoveryCandidate]:
    """Discover every linked manifestation inside the Puerto Rico table section."""
    parser = _TableParser()
    parser.feed(html)
    now = retrieved_utc or utc_now()
    in_pr = False
    last_project = ""
    out: list[DiscoveryCandidate] = []

    for row in parser.rows:
        text = _row_text(row)
        key = discovery_key(text)
        if key == "puerto rico" or key.startswith("puerto rico |"):
            in_pr = True
            continue
        if in_pr and ("u s virgin islands" in key or "us virgin islands" in key):
            break
        if not in_pr or not row:
            continue
        cells = [str(cell.get("text", "")) for cell in row]
        if cells and cells[0].strip():
            last_project = cells[0].strip()
        project = last_project
        if not project:
            continue
        doc_cells = row[2:] if len(row) >= 3 else row
        for cell in doc_cells:
            for link_text, href in cell.get("links", []):
                if not href:
                    continue
                document = (link_text or str(cell.get("text", ""))).strip() or "UNLABELED_LINK"
                out.append(
                    DiscoveryCandidate(
                        source_id=source_id,
                        source_page=source_page,
                        project_raw=project,
                        document_raw=document,
                        url_raw=href,
                        url_canonical=canonicalize_usace_url(href, base_url=source_page),
                        discovered_utc=now,
                        discovery_method="SAJ_ENVIRONMENTAL_DOCUMENTS_TABLE",
                    )
                )
    return out


def discover_contentdm_search(
    payload: dict[str, Any],
    *,
    source_id: str,
    source_page: str,
    retrieved_utc: str | None = None,
) -> list[DiscoveryCandidate]:
    """Convert CONTENTdm search JSON to manifestations without merging identities."""
    now = retrieved_utc or utc_now()
    items = payload.get("items") or payload.get("results") or []
    out: list[DiscoveryCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        collection = str(item.get("collectionAlias") or item.get("collection") or "").strip("/")
        pointer = item.get("itemLink") or item.get("pointer") or item.get("item_id") or item.get("item")
        title = str(item.get("title") or item.get("itemTitle") or "UNLABELED_ITEM")
        project = str(item.get("subCollection") or item.get("sub_collection") or "UNRESOLVED_PROJECT")
        if isinstance(pointer, str) and "/id/" in pointer:
            match = re.search(r"/collection/([^/]+)/id/(\d+)", pointer)
            if match:
                collection, pointer = match.group(1), match.group(2)
        if not collection or pointer in {None, ""}:
            continue
        item_url = f"https://usace.contentdm.oclc.org/digital/collection/{collection}/id/{pointer}/"
        out.append(
            DiscoveryCandidate(
                source_id=source_id,
                source_page=source_page,
                project_raw=project,
                document_raw=title,
                url_raw=item_url,
                url_canonical=item_url,
                discovered_utc=now,
                discovery_method="CONTENTDM_API_SEARCH",
            )
        )
    return out


def download_url(
    client: httpx.Client,
    url: str,
    *,
    source_id: str,
    output_dir: Path,
    filename: str | None = None,
) -> RetrievalReceipt:
    """Download one immutable manifestation and atomically freeze it on disk."""
    canonical_url = canonicalize_usace_url(url)
    response = client.get(canonical_url, follow_redirects=True)
    response.raise_for_status()
    payload = response.content
    digest = sha256_bytes(payload)
    name = filename or Path(urlsplit(str(response.url)).path).name or f"{digest}.bin"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / safe_name
    if final_path.exists() and sha256_bytes(final_path.read_bytes()) != digest:
        final_path = output_dir / f"{final_path.stem}__{digest[:12]}{final_path.suffix}"
    fd, temp_path = tempfile.mkstemp(prefix=".partial-", dir=output_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, final_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    receipt = RetrievalReceipt(
        source_id=source_id,
        url=canonical_url,
        retrieved_utc=utc_now(),
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        byte_count=len(payload),
        sha256=digest,
        final_url=str(response.url),
        output_path=str(final_path),
    )
    receipt_path = final_path.with_suffix(final_path.suffix + ".receipt.json")
    receipt_path.write_text(json.dumps(asdict(receipt), ensure_ascii=False, indent=2) + "\n")
    return receipt


def assert_arithmetic_closure(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in ("RETRIEVED", "EXCLUDED", "UNAVAILABLE", "UNRESOLVED")}
    total = 0
    for row in records:
        total += 1
        state = row.get("disposition")
        if state not in counts:
            raise ValueError(f"unclassified disposition: {state!r}")
        counts[state] += 1
    if total != sum(counts.values()):
        raise AssertionError("source arithmetic does not close")
    return {"source_total": total, **{k.lower(): v for k, v in counts.items()}}


def inspect_fixture_text(text: str) -> dict[str, Any]:
    """Regression helper for extracted PDF text; does not perform OCR."""
    appendix_headings = sorted(set(re.findall(r"APPENDIX\s+([A-Z])", text, flags=re.I)))
    boring_ids = sorted(
        set(re.findall(r"CB[- ]CUL[- ](\d{2})", text, flags=re.I)),
        key=lambda value: int(value),
    )
    return {
        "appendices_detected": [value.upper() for value in appendix_headings],
        "boring_ids": boring_ids,
        "has_geotechnical": bool(re.search(r"GEOTECHNICAL", text, flags=re.I)),
        "has_design_cost": bool(re.search(r"DESIGN\s+AND\s+COST", text, flags=re.I)),
    }
