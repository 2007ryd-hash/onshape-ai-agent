"""Command-line entry point for safe local V1 tests."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .demo import run_demo
from .doctor import inspect_installation
from .examples import ExampleError, run_named_example

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.callback()
def main() -> None:
    """Supervised engineering-to-Onshape automation commands."""


@app.command()
def demo(
    output: Path = typer.Option(
        Path("runs"),
        "--output",
        help="Directory that will contain the generated run directory.",
    ),
) -> None:
    """Run the network-free supervised pipeline demonstration."""

    summary = run_demo(output)
    typer.echo(json.dumps(summary, ensure_ascii=False, sort_keys=True))


@app.command()
def doctor(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit a machine-readable JSON report.",
    ),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root to inspect.",
    ),
) -> None:
    """Inspect the local installation without accessing provider credentials."""

    report = inspect_installation(repo_root)
    if json_output:
        typer.echo(report.model_dump_json())
    else:
        typer.echo(report.status)
        for check in report.checks:
            typer.echo(f"{check.status}: {check.name} - {check.detail}")
    if report.status != "READY_OFFLINE":
        raise typer.Exit(code=1)


@app.command("example")
def example_command(
    name: str = typer.Argument(help="Name of the repository example to run."),
    output: Path = typer.Option(Path("runs"), "--output"),
    repo_root: Path = typer.Option(Path("."), "--repo-root"),
) -> None:
    """Run one approved, network-free example."""

    try:
        summary = run_named_example(
            name,
            output,
            repo_root=repo_root.resolve(),
        )
    except ExampleError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    app()
