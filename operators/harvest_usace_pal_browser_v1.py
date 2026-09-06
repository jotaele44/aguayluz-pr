#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urljoin

from aguayluz.usace_corpus import canonicalize_usace_url, utc_now


def _require_selenium():
    try:
        from selenium import webdriver
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Selenium is required only for PAL browser execution; install selenium and a compatible Chrome/Chromium driver"
        ) from exc
    return webdriver, TimeoutException, By, Keys, EC, WebDriverWait


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_partitions(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("partitions")
    if not isinstance(rows, list) or not rows:
        raise ValueError("PAL partition manifest requires non-empty partitions")
    ids = [str(row.get("partition_id") or "") for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("PAL partition_id values must be present and unique")
    for row in rows:
        mode = row.get("mode", "simple")
        if mode not in {"simple", "advanced"}:
            raise ValueError(f"unsupported PAL search mode {mode!r}")
        expected_cap = int(row.get("expected_cap") or (250 if mode == "simple" else 200))
        canonical_cap = 250 if mode == "simple" else 200
        if expected_cap != canonical_cap:
            raise ValueError(f"PAL {mode} cap must be {canonical_cap}")
        if not str(row.get("query") or "").strip():
            raise ValueError("each PAL partition requires a nonblank query")
    return payload


def _visible_search_input(driver: Any):
    _, _, By, _, _, _ = _require_selenium()
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='search'], input[type='text'], input:not([type])")
    ranked = []
    for element in inputs:
        try:
            if not element.is_displayed() or not element.is_enabled():
                continue
        except Exception:
            continue
        context = " ".join(
            filter(
                None,
                [
                    element.get_attribute("placeholder"),
                    element.get_attribute("aria-label"),
                    element.get_attribute("name"),
                    element.get_attribute("id"),
                ],
            )
        ).casefold()
        score = 2 if "search" in context else 0
        ranked.append((score, element, context))
    if not ranked:
        raise RuntimeError("PAL visible search input not found")
    ranked.sort(key=lambda row: row[0], reverse=True)
    return ranked[0][1], ranked[0][2]


def _resource_links(driver: Any, base_url: str) -> list[dict[str, str]]:
    _, _, By, _, _, _ = _require_selenium()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
        href_raw = anchor.get_attribute("href") or ""
        href = canonicalize_usace_url(urljoin(base_url, href_raw))
        if "/resource?" not in href and "/resource/" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append({"anchor_text_raw": anchor.text, "href_raw": href_raw, "url_canonical": href})
    return out


def _result_total(body_text: str) -> int | None:
    patterns = [
        r"(?:showing\s+)?(?:\d+\s*[-–]\s*\d+\s+of\s+)?([\d,]+)\s+(?:results?|resources?|documents?)\b",
        r"\b([\d,]+)\s+items?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, body_text, flags=re.I)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _scroll_to_stability(driver: Any, *, max_cycles: int, stable_cycles: int, settle: float, base_url: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    if max_cycles < stable_cycles or stable_cycles < 1:
        raise ValueError("invalid PAL scroll stability bounds")
    receipts: list[dict[str, Any]] = []
    last_count = -1
    stable = 0
    links: list[dict[str, str]] = []
    for cycle in range(1, max_cycles + 1):
        links = _resource_links(driver, base_url)
        receipts.append({"cycle": cycle, "unique_resource_link_count": len(links)})
        if len(links) == last_count:
            stable += 1
        else:
            stable = 0
        if stable >= stable_cycles:
            return links, receipts
        last_count = len(links)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(settle)
    raise RuntimeError("PAL result list did not reach scroll stability within safety bound")


def run_partition(driver: Any, source_url: str, row: dict[str, Any], output_dir: Path, *, timeout: int, settle: float, max_scroll_cycles: int) -> dict[str, Any]:
    _, TimeoutException, By, Keys, EC, WebDriverWait = _require_selenium()
    partition_id = str(row["partition_id"])
    query = str(row["query"])
    mode = str(row.get("mode") or "simple")
    cap = int(row.get("expected_cap") or (250 if mode == "simple" else 200))
    driver.get(source_url)

    if mode == "advanced":
        # A visible Advanced Search control must exist; otherwise this partition cannot silently fall back to simple search.
        try:
            advanced = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//*[self::button or self::a][contains(normalize-space(.), 'Advanced')]")
                )
            )
            advanced.click()
        except TimeoutException as exc:
            raise RuntimeError("PAL Advanced Search requested but control not found") from exc

    search, search_context = _visible_search_input(driver)
    search.clear()
    search.send_keys(query)
    search.send_keys(Keys.ENTER)
    time.sleep(settle)

    links, scroll_receipts = _scroll_to_stability(
        driver,
        max_cycles=max_scroll_cycles,
        stable_cycles=2,
        settle=settle,
        base_url=source_url,
    )
    body = driver.find_element(By.TAG_NAME, "body").text
    total = _result_total(body)
    html = driver.page_source
    part_dir = output_dir / partition_id
    part_dir.mkdir(parents=True, exist_ok=True)
    html_path = part_dir / "results.html"
    html_path.write_text(html, encoding="utf-8")
    with (part_dir / "resource_links.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["anchor_text_raw", "href_raw", "url_canonical"])
        writer.writeheader()
        writer.writerows(links)

    state = "PASS_PARTITION_EXHAUSTION"
    if total is None:
        state = "UNRESOLVED_RESULT_TOTAL_NOT_BOUND"
    elif total >= cap:
        state = "UNRESOLVED_PUBLIC_SEARCH_CAP_REACHED"
    elif len(links) < total:
        state = "UNRESOLVED_RESULT_LINK_COUNT_SHORT"
    elif len(links) > total:
        state = "UNRESOLVED_RESULT_LINK_COUNT_OVERFLOW"

    return {
        "partition_id": partition_id,
        "query_raw": query,
        "mode": mode,
        "public_cap": cap,
        "search_input_context": search_context,
        "resolved_url": driver.current_url,
        "reported_total": total,
        "unique_resource_link_count": len(links),
        "html_sha256": sha256_text(html),
        "html_path": str(html_path),
        "scroll_receipts": scroll_receipts,
        "coverage_basis": row.get("coverage_basis"),
        "coverage_interval": row.get("coverage_interval"),
        "state": state,
    }


def build_driver(headless: bool):
    webdriver, *_ = _require_selenium()
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)


def main() -> int:
    parser = argparse.ArgumentParser(description="PAL bounded partition browser harvester")
    parser.add_argument("--partitions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="https://publibrary.sec.usace.army.mil/search")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--settle", type=float, default=1.5)
    parser.add_argument("--max-scroll-cycles", type=int, default=1000)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    manifest = load_partitions(args.partitions)
    args.output.mkdir(parents=True, exist_ok=True)
    driver = build_driver(not args.headed)
    receipts: list[dict[str, Any]] = []
    try:
        for row in manifest["partitions"]:
            try:
                receipts.append(
                    run_partition(
                        driver,
                        args.url,
                        row,
                        args.output,
                        timeout=args.timeout,
                        settle=args.settle,
                        max_scroll_cycles=args.max_scroll_cycles,
                    )
                )
            except Exception as exc:
                receipts.append(
                    {
                        "partition_id": row["partition_id"],
                        "query_raw": row.get("query"),
                        "mode": row.get("mode", "simple"),
                        "state": "UNAVAILABLE_RUNTIME_OR_UI_SCHEMA",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    finally:
        driver.quit()

    nonpass = [row for row in receipts if not str(row.get("state", "")).startswith("PASS_")]
    coverage_proof = str(manifest.get("coverage_proof_state") or "UNRESOLVED")
    overall = (
        "PASS_EXHAUSTIVE_DECLARED_PARTITIONS"
        if not nonpass and coverage_proof == "PASS"
        else "OPEN_PARTITION_OR_COVERAGE_RESIDUE"
    )
    snapshot = {
        "snapshot_version": "1.0.0",
        "created_utc": utc_now(),
        "source_id": "iwr_project_assistance_library",
        "source_url": args.url,
        "partition_manifest": str(args.partitions),
        "partition_count": len(receipts),
        "coverage_proof_state": coverage_proof,
        "partition_receipts": receipts,
        "state": overall,
        "rule": "PAL public result caps are 250 simple / 200 advanced; any partition at cap, without a bound total, or without explicit gap-free partition coverage fails closed.",
    }
    (args.output / "pal_browser_receipt.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0 if overall.startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
