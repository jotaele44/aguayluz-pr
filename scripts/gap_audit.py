#!/usr/bin/env python3
"""Compute the repo-wide gap snapshot used by docs/gap_analysis.md.

Outputs deterministic counts that the drift guard can pin: schemas, CLI
subcommands, test files, scripts. Run with `--check` to fail when the
committed doc diverges from the live audit.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aguayluz import REPO_ROOT, SCHEMAS_DIR  # noqa: E402

GAP_DOC = REPO_ROOT / "docs" / "gap_analysis.md"

# Markers in the doc the audit injects between.
COUNTS_BEGIN = "<!-- gap-counts-begin -->"
COUNTS_END = "<!-- gap-counts-end -->"


def _count_schemas() -> int:
    return len(list(SCHEMAS_DIR.glob("*.schema.json")))


def _count_cli_subcommands() -> int:
    cli = (REPO_ROOT / "src" / "aguayluz" / "cli.py").read_text(encoding="utf-8")
    # Match both @app.command("name") and @app.command()
    named = len(re.findall(r'@app\.command\("[^"]+"\)', cli))
    plain = len(re.findall(r"@app\.command\(\)\s*\ndef \w+", cli))
    return named + plain


def _count_scripts() -> int:
    return len([p for p in (REPO_ROOT / "scripts").glob("*.py") if p.name != "__init__.py"])


def _count_tests() -> int:
    return len(list((REPO_ROOT / "tests").glob("test_*.py")))


def _count_source_modules(layer: str) -> int:
    layer_path = REPO_ROOT / "src" / "aguayluz" / layer
    if not layer_path.exists():
        return 0
    return len([p for p in layer_path.glob("*.py") if p.name != "__init__.py"])


def _count_waters_endpoint_wrappers() -> int:
    text = (REPO_ROOT / "src" / "aguayluz" / "waters" / "endpoints.py").read_text(encoding="utf-8")
    # Public functions are `def <name>(client: WatersClient, ...)` style.
    return len(re.findall(r"^def [a-z_][a-z0-9_]*\(\s*client:", text, re.MULTILINE))


def build_counts() -> dict[str, int]:
    return {
        "schemas": _count_schemas(),
        "cli_subcommands": _count_cli_subcommands(),
        "scripts": _count_scripts(),
        "test_files": _count_tests(),
        "waters_endpoints_wrapped": _count_waters_endpoint_wrappers(),
        "ingest_adapters": _count_source_modules("ingest"),
        "analysis_modules": _count_source_modules("analysis"),
    }


def format_counts_block(counts: dict[str, int]) -> str:
    lines = [COUNTS_BEGIN, "| Inventory | Count |", "|---|---|"]
    for key in sorted(counts):
        lines.append(f"| `{key}` | {counts[key]} |")
    lines.append(COUNTS_END)
    return "\n".join(lines)


def update_doc(doc_path: Path, counts: dict[str, int]) -> bool:
    """Insert/replace the counts block. Returns True if the file changed."""
    text = doc_path.read_text(encoding="utf-8")
    block = format_counts_block(counts)
    if COUNTS_BEGIN in text and COUNTS_END in text:
        new_text = re.sub(
            rf"{re.escape(COUNTS_BEGIN)}.*?{re.escape(COUNTS_END)}",
            block,
            text,
            flags=re.DOTALL,
        )
    else:
        new_text = text + "\n\n" + block + "\n"
    changed = new_text != text
    if changed:
        doc_path.write_text(new_text, encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Audit repo inventory + drift-check the gap analysis doc")
    p.add_argument("--check", action="store_true",
                   help="Exit non-zero if docs/gap_analysis.md diverges from the live audit")
    args = p.parse_args(argv)

    counts = build_counts()
    if not GAP_DOC.exists():
        print("gap_audit: docs/gap_analysis.md missing — please create it first", file=sys.stderr)
        return 2

    if args.check:
        current = GAP_DOC.read_text(encoding="utf-8")
        block = format_counts_block(counts)
        if block not in current:
            print(
                "gap_audit: counts block is stale; regenerate with "
                "`python scripts/gap_audit.py` and commit:",
                file=sys.stderr,
            )
            print(block, file=sys.stderr)
            return 1
        print("gap_audit: counts in sync with code")
        return 0

    changed = update_doc(GAP_DOC, counts)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"{'updated' if changed else 'unchanged'}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
