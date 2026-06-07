"""Typer CLI entry point — `aguayluz <subcommand>`.

Subcommands wrap the scripts in `scripts/` so users can either:
  - call `aguayluz smoke --demo-mode` after `pip install -e .`, or
  - call `python scripts/smoke_test.py --demo-mode` from a fresh checkout
    (iOS a-Shell, CI bootstrap, etc.).

Both paths share the same logic — the scripts are thin shims around the CLI
helpers below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from . import OUTPUTS_DIR

app = typer.Typer(
    add_completion=False,
    help="Puerto Rico utility infrastructure intelligence producer (aguayluz-pr).",
    no_args_is_help=True,
)


@app.command("validate-repo")
def validate_repo() -> None:
    """Run the eight federation validation gates (G01-G08)."""
    from .validation import assert_schemas_resolvable, run_gates

    assert_schemas_resolvable()
    report = run_gates()
    rows = report.as_rows()
    width_id = max(len(r[0]) for r in rows)
    width_status = max(len(r[1]) for r in rows)
    typer.echo(f"\n{'GATE'.ljust(width_id)}  {'STATUS'.ljust(width_status)}  DETAILS")
    typer.echo(f"{'-' * width_id}  {'-' * width_status}  -------")
    for gate_id, status, details in rows:
        typer.echo(f"{gate_id.ljust(width_id)}  {status.ljust(width_status)}  {details}")

    blocking_failures = [r for r in report.results if r.is_blocking_failure]
    typer.echo("")
    if blocking_failures:
        typer.echo(f"FAIL — {len(blocking_failures)} blocking gate(s) failed.")
        raise typer.Exit(1)
    typer.echo("OK — no blocking gate failures.")


@app.command()
def smoke(
    demo_mode: bool = typer.Option(
        False, "--demo-mode",
        help="Load the recorded WATERS fixture instead of calling the live API.",
    ),
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
) -> None:
    """Run the end-to-end pipeline against Lago La Plata (live or demo)."""
    # Defer import so subcommands without scripts/ on sys.path still load fast.
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import smoke_test as _smoke  # type: ignore[import-not-found]

    raise typer.Exit(_smoke.run(demo_mode, outputs_dir))


@app.command("build-manifest")
def build_manifest(outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir")) -> None:
    """Aggregate source references into outputs/source_manifest.json."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import build_source_manifest as _bm  # type: ignore[import-not-found]

    sys.argv = ["build_source_manifest.py", "--outputs-dir", str(outputs_dir)]
    raise typer.Exit(_bm.main())


@app.command("ingest-frs")
def ingest_frs(
    input_path: Path = typer.Option(..., "--input", help="EPA FRS JSON response"),
    demo_mode: bool = typer.Option(False, "--demo-mode"),
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
    vector: str = typer.Option("AGUAYLUZ_INGEST_PUBLIC_ASSETS", "--vector"),
) -> None:
    """Ingest EPA Facility Registry Service records and snap each to NHDPlus."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import ingest_facilities as _ingest  # type: ignore[import-not-found]

    argv = [
        "--input", str(input_path),
        "--source", "frs",
        "--outputs-dir", str(outputs_dir),
        "--vector", vector,
    ]
    if demo_mode:
        argv.append("--demo-mode")
    raise typer.Exit(_ingest.main(argv))


@app.command("ingest-fema")
def ingest_fema(
    input_path: Path = typer.Option(..., "--input", help="FEMA OpenFEMA JSON response"),
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
    vector: str = typer.Option("AGUAYLUZ_INGEST_SERVICE_EVENTS", "--vector"),
) -> None:
    """Ingest FEMA Public Assistance records as service events (no WATERS call)."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import ingest_events as _ingest_events  # type: ignore[import-not-found]

    argv = [
        "--input", str(input_path),
        "--source", "fema",
        "--outputs-dir", str(outputs_dir),
        "--vector", vector,
    ]
    raise typer.Exit(_ingest_events.main(argv))


@app.command("build-graph")
def build_graph(
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
    use_waters: bool = typer.Option(False, "--use-waters",
        help="Also emit downstream_of edges via WATERS (requires EPA_WATERS_API_KEY)."),
    vector: str = typer.Option("AGUAYLUZ_BUILD_DEPENDENCY_GRAPH", "--vector"),
) -> None:
    """Wire assets + events into a dependency graph and emit the bridge summary."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import build_dependency_graph as _bg  # type: ignore[import-not-found]

    argv = ["--outputs-dir", str(outputs_dir), "--vector", vector]
    if use_waters:
        argv.append("--use-waters")
    raise typer.Exit(_bg.main(argv))


@app.command()
def reconcile(
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
    vector: str = typer.Option("AGUAYLUZ_RECONCILE_PROJECT_STATUS", "--vector"),
) -> None:
    """Cross-check FEMA project status vs asset operational status."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import reconcile_status as _rs  # type: ignore[import-not-found]

    raise typer.Exit(_rs.main(["--outputs-dir", str(outputs_dir), "--vector", vector]))


@app.command()
def snapshot(
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
    run_id: str = typer.Option(None, "--run-id"),
    slug: str = typer.Option("snapshot", "--slug"),
) -> None:
    """Snapshot current outputs/ entity files under outputs/history/<run_id>/."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import snapshot_run as _sn  # type: ignore[import-not-found]

    argv = ["--outputs-dir", str(outputs_dir), "--slug", slug]
    if run_id:
        argv += ["--run-id", run_id]
    raise typer.Exit(_sn.main(argv))


@app.command()
def diff(
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
    run_from: str = typer.Option(None, "--from", help="Source run_id"),
    run_to: str = typer.Option(None, "--to", help="Target run_id"),
) -> None:
    """Diff two snapshotted runs; writes outputs/run_diff.json."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import diff_runs as _df  # type: ignore[import-not-found]

    argv = ["--outputs-dir", str(outputs_dir)]
    if run_from:
        argv += ["--from", run_from]
    if run_to:
        argv += ["--to", run_to]
    raise typer.Exit(_df.main(argv))


@app.command()
def delineate(
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
    demo_mode: bool = typer.Option(False, "--demo-mode"),
    max_calls: int = typer.Option(10, "--max-calls"),
    vector: str = typer.Option("AGUAYLUZ_DELINEATE_WATERSHEDS", "--vector"),
) -> None:
    """Delineate the upstream watershed of every water/wastewater asset."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import delineate_watersheds as _del  # type: ignore[import-not-found]

    argv = [
        "--outputs-dir", str(outputs_dir),
        "--vector", vector,
        "--max-calls", str(max_calls),
    ]
    if demo_mode:
        argv.append("--demo-mode")
    raise typer.Exit(_del.main(argv))


@app.command("export-base44")
def export_base44(
    run_id: str = typer.Option(..., "--run-id", help="YYYYMMDDTHHMMSSZ_slug"),
    vector: str = typer.Option(
        "AGUAYLUZ_WATER_POWER_INFRASTRUCTURE_INTELLIGENCE", "--vector"
    ),
    outputs_dir: Path = typer.Option(OUTPUTS_DIR, "--outputs-dir"),
) -> None:
    """Build and write outputs/base44_export.json."""
    _scripts = Path(__file__).resolve().parent.parent.parent / "scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    import export_base44_summary as _e  # type: ignore[import-not-found]

    sys.argv = [
        "export_base44_summary.py",
        "--run-id", run_id,
        "--vector", vector,
        "--outputs-dir", str(outputs_dir),
    ]
    raise typer.Exit(_e.main())


if __name__ == "__main__":  # pragma: no cover
    app()
