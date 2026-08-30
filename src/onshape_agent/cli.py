"""Command-line entry point for safe local V1 tests."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .demo import run_demo

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


if __name__ == "__main__":
    app()
