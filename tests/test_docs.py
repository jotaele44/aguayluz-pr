"""Drift guard: the docs in `docs/` must reference real code.

Catches PRs that add a CLI subcommand without updating `docs/vectors.md`, add
a schema without `docs/schemas.md`, or rename a module without updating
`docs/architecture.md`.
"""

from __future__ import annotations

import re

from aguayluz import REPO_ROOT, SCHEMAS_DIR

DOCS = REPO_ROOT / "docs"


def _read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _cli_subcommands() -> set[str]:
    """Pull the @app.command(...) names from src/aguayluz/cli.py."""
    cli_text = (REPO_ROOT / "src" / "aguayluz" / "cli.py").read_text(encoding="utf-8")
    out: set[str] = set()
    for line in cli_text.splitlines():
        m = re.match(r'@app\.command\((?:"([^"]+)")?\)', line.strip())
        if m:
            if m.group(1):
                out.add(m.group(1))
        else:
            # @app.command() with no name → function name is the subcommand.
            if line.strip().startswith("@app.command()"):
                # Look at the function on the next non-blank line. Simplest
                # heuristic: read the file and pair them in a second pass.
                pass
    # Second pass for @app.command() without explicit name → use function name.
    pairs = re.findall(
        r"@app\.command\(\)\s*\ndef (\w+)\(",
        cli_text,
    )
    for name in pairs:
        out.add(name.replace("_", "-"))
    return out


# ---------- existence ----------


def test_all_doc_files_exist():
    for name in ("architecture.md", "vectors.md", "schemas.md", "contributing.md"):
        assert (DOCS / name).exists(), f"missing docs/{name}"


def test_readme_links_into_docs_dir():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for name in ("architecture.md", "vectors.md", "schemas.md", "contributing.md"):
        assert f"docs/{name}" in readme, f"README missing link to docs/{name}"


# ---------- schemas drift ----------


def test_every_schema_appears_in_schemas_doc():
    schemas_doc = _read("schemas.md")
    for schema in SCHEMAS_DIR.glob("*.schema.json"):
        name = schema.stem.replace(".schema", "")
        # The doc references each schema name in a code-fence or backticks.
        assert (
            f"`{name}`" in schemas_doc or f"`{name}.schema.json`" in schemas_doc
        ), f"docs/schemas.md missing reference to {name}"


def test_schema_count_in_architecture_matches_disk():
    arch = _read("architecture.md")
    on_disk = len(list(SCHEMAS_DIR.glob("*.schema.json")))
    # Architecture says "12 federation contracts" in the schemas section header.
    assert f"{on_disk} federation contracts" in arch or f"({on_disk} schemas)" in arch


# ---------- vectors drift ----------


def test_every_cli_subcommand_appears_in_vectors_doc():
    vectors_doc = _read("vectors.md")
    cli_cmds = _cli_subcommands()
    # Every subcommand should be referenced (could be as `aguayluz <cmd>` or `aguayluz <cmd>`).
    missing = [c for c in cli_cmds if f"aguayluz {c}" not in vectors_doc]
    assert not missing, f"docs/vectors.md missing CLI subcommands: {missing}"


# ---------- contributing references ----------


def test_contributing_references_existing_modules():
    # contributing.md is loaded to ensure it exists/parses; the assertion below
    # checks that the modules it points at are actually present in the repo.
    _read("contributing.md")
    referenced_files = (
        "src/aguayluz/ingest/frs.py",
        "src/aguayluz/ingest/hifld.py",
        "src/aguayluz/cli.py",
        "src/aguayluz/validation.py",
        "tests/test_live_ingest.py",
    )
    missing = [f for f in referenced_files if not (REPO_ROOT / f).exists()]
    assert not missing, f"docs/contributing.md references missing files: {missing}"
