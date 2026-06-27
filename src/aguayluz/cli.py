"""AguaYLuz command-line interface — the ``aguayluz`` console script.

``pyproject.toml`` declares ``[project.scripts] aguayluz = "aguayluz.cli:app"``;
this module provides that ``app``. Wraps the federation validation gates
(G01-G08) so they are reachable both as ``aguayluz validate`` and via
``scripts/validate_repo.py``.
"""
from __future__ import annotations

import json

import typer

from . import OUTPUTS_DIR, __version__
from .validation import assert_schemas_resolvable, run_gates

app = typer.Typer(
    help="AguaYLuz — Puerto Rico water/power/utility infrastructure intelligence producer.",
    no_args_is_help=True,
    add_completion=False,
)

alerts_app = typer.Typer(
    help="Operational alert system (build SQLite, validate VAL-001..010, export GeoJSON).",
    no_args_is_help=True,
)
app.add_typer(alerts_app, name="alerts")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def validate() -> None:
    """Run the eight federation validation gates (G01-G08).

    Exits non-zero on any blocking (FAIL) gate, matching scripts/validate_repo.py.
    """
    assert_schemas_resolvable()
    report = run_gates()
    width = max((len(gid) for gid, _, _ in report.as_rows()), default=4)
    for gate_id, status, details in report.as_rows():
        typer.echo(f"{gate_id.ljust(width)}  {status:5}  {details}")
    blocking = [r for r in report.results if r.is_blocking_failure]
    if blocking:
        typer.echo(f"\nFAIL — {len(blocking)} blocking gate(s).")
        raise typer.Exit(code=1)
    typer.echo("\nOK — no blocking gate failures.")


@alerts_app.command("build")
def alerts_build(
    db: str = typer.Option(str(OUTPUTS_DIR / "alert_system.sqlite"), help="SQLite output path."),
    in_memory: bool = typer.Option(False, "--in-memory", help="Build in memory; do not write the DB."),
) -> None:
    """Build the alert SQLite DB from the DDL + seeds and emit GeoJSON."""
    from .alert_db import build_sqlite, events_to_geojson, load_events

    events = load_events()
    target = ":memory:" if in_memory else db
    conn = build_sqlite(target, events=events)
    conn.close()
    geo = events_to_geojson(events)
    (OUTPUTS_DIR / "alert_events.geojson").parent.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "alert_events.geojson").write_text(
        json.dumps(geo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    typer.echo(f"built {target}; {len(events)} events, {len(geo['features'])} geo feature(s)")


@alerts_app.command("validate")
def alerts_validate() -> None:
    """Run VAL-001..010 over the seed alert events. Exits non-zero on rejection."""
    from .alert_db import validate_seed_events

    results = validate_seed_events()
    rejected = [r for r in results if not r.valid]
    for r in results:
        for v in r.violations:
            typer.echo(f"{r.alert_id}  {v.rule_id}  {v.severity:8}  {v.message}")
    if rejected:
        typer.echo(f"\nFAIL — {len(rejected)} alert(s) rejected.")
        raise typer.Exit(code=1)
    typer.echo(f"OK — {len(results)} alert(s) structurally valid.")


if __name__ == "__main__":
    app()
