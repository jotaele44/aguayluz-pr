"""AguaYLuz command-line interface — the ``aguayluz`` console script.

``pyproject.toml`` declares ``[project.scripts] aguayluz = "aguayluz.cli:app"``;
this module provides that ``app``. Wraps the federation validation gates
(G01-G08) so they are reachable both as ``aguayluz validate`` and via
``scripts/validate_repo.py``.
"""
from __future__ import annotations

import typer

from . import __version__
from .validation import assert_schemas_resolvable, run_gates

app = typer.Typer(
    help="AguaYLuz — Puerto Rico water/power/utility infrastructure intelligence producer.",
    no_args_is_help=True,
    add_completion=False,
)


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


if __name__ == "__main__":
    app()
