#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from aguayluz.usace_corpus import utc_now


def _require_selenium():
    try:
        from selenium import webdriver
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import Select, WebDriverWait
    except ImportError as exc:  # pragma: no cover - depends on execution host
        raise RuntimeError(
            "Selenium is required only for dynamic USACE sources; install selenium and a compatible Chrome/Chromium driver"
        ) from exc
    return webdriver, TimeoutException, By, EC, Select, WebDriverWait


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _with_query(url: str, **values: str) -> str:
    split = urlsplit(url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def _click_text(driver: Any, text: str, *, timeout: int, optional: bool = False) -> bool:
    _, TimeoutException, By, EC, _, WebDriverWait = _require_selenium()
    xpath = (
        "//*[self::button or self::a or @role='button']"
        f"[contains(normalize-space(.), {json.dumps(text)})]"
    )
    try:
        element = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.click()
        return True
    except TimeoutException:
        if optional:
            return False
        raise RuntimeError(f"required UI control not found/clickable: {text!r}")


def _select_html_option(driver: Any, label_tokens: Iterable[str], option_tokens: Iterable[str]) -> dict[str, Any]:
    """Use only native <select> controls; custom comboboxes remain explicitly unresolved."""
    _, _, By, _, Select, _ = _require_selenium()
    labels = [token.casefold() for token in label_tokens]
    options = [token.casefold() for token in option_tokens]
    for element in driver.find_elements(By.TAG_NAME, "select"):
        context = " ".join(
            filter(
                None,
                [
                    element.get_attribute("name"),
                    element.get_attribute("id"),
                    element.get_attribute("aria-label"),
                    element.get_attribute("title"),
                ],
            )
        ).casefold()
        if labels and not any(token in context for token in labels):
            continue
        select = Select(element)
        for opt in select.options:
            text = (opt.text or "").strip()
            value = (opt.get_attribute("value") or "").strip()
            probe = f"{text} {value}".casefold()
            if any(token in probe for token in options):
                select.select_by_visible_text(text)
                return {"state": "PASS_NATIVE_SELECT", "label_context": context, "selected_text": text, "selected_value": value}
    return {"state": "UNRESOLVED_CUSTOM_OR_MISSING_FILTER"}


def _table_rows(driver: Any) -> tuple[list[str], list[dict[str, Any]]]:
    _, _, By, _, _, _ = _require_selenium()
    tables = driver.find_elements(By.TAG_NAME, "table")
    if not tables:
        raise RuntimeError("no HTML table found after entering Table View")
    # Prefer the table with the largest number of body rows.
    ranked = sorted(tables, key=lambda t: len(t.find_elements(By.CSS_SELECTOR, "tbody tr")), reverse=True)
    table = ranked[0]
    headers = [cell.text.strip() for cell in table.find_elements(By.CSS_SELECTOR, "thead th")]
    if not headers:
        first = table.find_elements(By.CSS_SELECTOR, "tr")
        if first:
            headers = [cell.text.strip() for cell in first[0].find_elements(By.CSS_SELECTOR, "th,td")]
    rows: list[dict[str, Any]] = []
    body_rows = table.find_elements(By.CSS_SELECTOR, "tbody tr") or table.find_elements(By.CSS_SELECTOR, "tr")[1:]
    for tr in body_rows:
        cells = [td.text for td in tr.find_elements(By.CSS_SELECTOR, "td")]
        links = []
        for anchor in tr.find_elements(By.CSS_SELECTOR, "a[href]"):
            links.append({"text_raw": anchor.text, "href_raw": anchor.get_attribute("href")})
        if not cells and not links:
            continue
        rows.append({"cells_raw": cells, "links": links})
    return headers, rows


def _next_button(driver: Any):
    _, _, By, _, _, _ = _require_selenium()
    selectors = [
        "button[aria-label*='Next']",
        "a[aria-label*='Next']",
        "button[title*='Next']",
        "a[title*='Next']",
    ]
    for selector in selectors:
        found = driver.find_elements(By.CSS_SELECTOR, selector)
        if found:
            return found[0]
    candidates = driver.find_elements(
        By.XPATH,
        "//*[self::button or self::a][normalize-space(.)='Next' or normalize-space(.)='>' or normalize-space(.)='›']",
    )
    return candidates[0] if candidates else None


def _disabled(element: Any) -> bool:
    if element is None:
        return True
    value = (element.get_attribute("disabled") or "").casefold()
    aria = (element.get_attribute("aria-disabled") or "").casefold()
    classes = (element.get_attribute("class") or "").casefold()
    return value in {"true", "disabled"} or aria == "true" or "disabled" in classes


def capture_table_pages(driver: Any, output_dir: Path, *, max_pages: int, settle_seconds: float) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Capture paginated table pages with duplicate-page and max-page fail-closed gates."""
    if max_pages < 1:
        raise ValueError("max_pages must be >=1")
    output_dir.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    page_receipts: list[dict[str, Any]] = []
    canonical_headers: list[str] | None = None
    seen_signatures: set[str] = set()
    exhausted = False

    for page_no in range(1, max_pages + 1):
        time.sleep(settle_seconds)
        headers, rows = _table_rows(driver)
        if canonical_headers is None:
            canonical_headers = headers
        elif headers != canonical_headers:
            raise RuntimeError(f"table headers changed at page {page_no}")
        signature = sha256_text(json.dumps(rows, ensure_ascii=False, sort_keys=True))
        if signature in seen_signatures:
            raise RuntimeError(f"pagination repeated a prior row set at page {page_no}")
        seen_signatures.add(signature)
        html = driver.page_source
        html_path = output_dir / f"page_{page_no:05d}.html"
        html_path.write_text(html, encoding="utf-8")
        page_receipts.append(
            {
                "page": page_no,
                "url": driver.current_url,
                "row_count": len(rows),
                "row_signature_sha256": signature,
                "html_sha256": sha256_text(html),
                "html_path": str(html_path),
            }
        )
        for index, row in enumerate(rows):
            all_rows.append({"page": page_no, "row_index": index, **row})
        nxt = _next_button(driver)
        if _disabled(nxt):
            exhausted = True
            break
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", nxt)
        nxt.click()
    if not exhausted:
        raise RuntimeError(f"pagination did not prove exhaustion within max_pages={max_pages}")
    return canonical_headers or [], all_rows, page_receipts


def _write_rows(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["page", "row_index", *headers, "links_json"])
        for row in rows:
            cells = list(row["cells_raw"])
            if len(cells) < len(headers):
                cells += [""] * (len(headers) - len(cells))
            writer.writerow([row["page"], row["row_index"], *cells[: len(headers)], json.dumps(row["links"], ensure_ascii=False)])


def run_rrs(driver: Any, args: argparse.Namespace) -> dict[str, Any]:
    driver.get(args.url)
    _click_text(driver, "I Accept", timeout=args.timeout, optional=True)
    _click_text(driver, "Table View", timeout=args.timeout)
    # Native filters are attempted but are not assumed to exist; custom React controls remain a blocker receipt.
    state_filter = _select_html_option(driver, ["state"], ["puerto rico", "pr"])
    district_filter = _select_html_option(driver, ["district"], ["caribbean", "saa"])
    headers, rows, pages = capture_table_pages(
        driver, args.output / "rrs_pages", max_pages=args.max_pages, settle_seconds=args.settle
    )
    scope_pass = state_filter["state"].startswith("PASS_")
    state = "PASS_EXHAUSTIVE_PR_SCOPE" if scope_pass else "UNRESOLVED_PR_SCOPE_FILTER"
    _write_rows(args.output / "rrs_rows.csv", headers, rows)
    return {
        "source_id": "rrs_public_notices_pr",
        "adapter": "selenium_table_v1",
        "url": args.url,
        "retrieved_utc": utc_now(),
        "headers_raw": headers,
        "row_count": len(rows),
        "page_count": len(pages),
        "state_filter": state_filter,
        "district_filter": district_filter,
        "page_receipts": pages,
        "state": state,
    }


ORM_TYPES = {
    "jds": "AJD",
    "s408": "Section 408",
}


def run_orm(driver: Any, args: argparse.Namespace) -> dict[str, Any]:
    type_receipts: list[dict[str, Any]] = []
    total_rows = 0
    all_headers: dict[str, list[str]] = {}
    # Only query codes independently evidenced in authoritative/public indexed URLs are prebound.
    # Other UI content classes remain unresolved instead of inventing query codes.
    for type_code, label in ORM_TYPES.items():
        url = _with_query(args.url, mode="table", org="SAA", type=type_code)
        driver.get(url)
        _click_text(driver, "Table View", timeout=args.timeout, optional=True)
        state_filter = _select_html_option(driver, ["state"], ["puerto rico", "pr"])
        out_dir = args.output / f"orm_{type_code}_pages"
        headers, rows, pages = capture_table_pages(
            driver, out_dir, max_pages=args.max_pages, settle_seconds=args.settle
        )
        _write_rows(args.output / f"orm_{type_code}_rows.csv", headers, rows)
        all_headers[type_code] = headers
        total_rows += len(rows)
        type_receipts.append(
            {
                "type_code": type_code,
                "label": label,
                "url": url,
                "row_count": len(rows),
                "page_count": len(pages),
                "state_filter": state_filter,
                "state": (
                    "PASS_EXHAUSTIVE_PR_SCOPE"
                    if state_filter["state"].startswith("PASS_")
                    else "UNRESOLVED_PR_SCOPE_FILTER"
                ),
                "page_receipts": pages,
            }
        )
    missing_classes = [
        "Final IP",
        "Pending IP",
        "NEPA EA",
        "NEPA EIS",
        "Emergency",
        "214/Other",
        "DWHS",
    ]
    return {
        "source_id": "orm_public_pr",
        "adapter": "selenium_table_v1",
        "base_url": args.url,
        "retrieved_utc": utc_now(),
        "prebound_type_codes": ORM_TYPES,
        "unbound_type_classes": missing_classes,
        "type_receipts": type_receipts,
        "row_count": total_rows,
        "headers_by_type": all_headers,
        "state": "UNRESOLVED_ORM_TYPE_CODE_UNIVERSE" if missing_classes else "PASS_EXHAUSTIVE_PR_SCOPE",
    }


def build_driver(headless: bool):
    webdriver, *_ = _require_selenium()
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dynamic browser harvester for USACE RRS/ORM public sources")
    parser.add_argument("source", choices=["rrs", "orm"])
    parser.add_argument("--url")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=10000)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--settle", type=float, default=1.5)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    if args.url is None:
        args.url = (
            "https://rrs.usace.army.mil/rrs/public-notices"
            if args.source == "rrs"
            else "https://permits.ops.usace.army.mil/orm-public"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    driver = build_driver(not args.headed)
    try:
        receipt = run_rrs(driver, args) if args.source == "rrs" else run_orm(driver, args)
    finally:
        driver.quit()
    (args.output / f"{args.source}_browser_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if str(receipt["state"]).startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
