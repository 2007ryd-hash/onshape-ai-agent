"""Command-line entry point for safe local V1 tests."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .contracts import TransportReceipt
from .demo import run_demo
from .doctor import inspect_installation
from .examples import ExampleError, run_named_example
from .live_service import LiveService, inspect_local_auth

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
auth_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
live_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(auth_app, name="auth")
app.add_typer(live_app, name="live")


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
    live: bool = typer.Option(
        False,
        "--live",
        help="Explicitly validate the existing Onshape MCP session.",
    ),
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
    """Inspect the local installation, optionally using an explicit live probe."""

    report = inspect_installation(repo_root, live=live)
    if json_output:
        typer.echo(report.model_dump_json())
    else:
        typer.echo(report.status)
        for check in report.checks:
            typer.echo(f"{check.status}: {check.name} - {check.detail}")
    if report.status not in {"READY_OFFLINE", "READY_LIVE"}:
        raise typer.Exit(code=1)


@auth_app.command("status")
def auth_status(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit a machine-readable local presence summary.",
    ),
    config_dir: Path | None = typer.Option(
        None,
        "--config-dir",
        help="Optional upstream MCP config directory to inspect by presence only.",
    ),
) -> None:
    """Show local Onshape MCP config/token presence without network access."""

    summary = inspect_local_auth(config_dir)
    if json_output:
        typer.echo(summary.model_dump_json())
        return
    typer.echo(summary.status)
    typer.echo(f"configured: {summary.configured}")
    typer.echo(f"authenticated: {summary.authenticated}")
    typer.echo(f"config_present: {summary.config_present}")
    typer.echo(f"tokens_present: {summary.tokens_present}")
    typer.echo("network_request_sent: False")


def _emit_receipt(receipt: TransportReceipt, *, json_output: bool) -> None:
    """Print only the typed, body-free receipt returned by the live service."""

    if json_output:
        typer.echo(receipt.model_dump_json())
    else:
        typer.echo(receipt.operation)
        typer.echo(f"status: {receipt.status}")
        typer.echo(f"network_request_sent: {receipt.network_request_sent}")
        typer.echo(f"readback_verified: {receipt.readback_verified}")
        for key, value in receipt.evidence_summary.items():
            typer.echo(f"{key}: {value}")
        if receipt.error_code is not None:
            typer.echo(f"error_code: {receipt.error_code}")


def _exit_for_receipt(receipt: TransportReceipt) -> None:
    if receipt.status != "SUCCEEDED":
        raise typer.Exit(code=1)


@live_app.command("list-documents")
def list_documents(
    limit: int = typer.Option(
        1,
        "--limit",
        min=1,
        max=100,
        help="Maximum number of documents to request (1-100).",
    ),
    json_output: bool = typer.Option(
        True,
        "--json/--text",
        help="Emit a machine-readable safe receipt (default: JSON).",
    ),
) -> None:
    """Run the explicit, bounded live document discovery read."""

    receipt = LiveService().list_documents(limit)
    _emit_receipt(receipt, json_output=json_output)
    _exit_for_receipt(receipt)


@live_app.command("read-document")
def read_document(
    document_id: str = typer.Option(
        ...,
        "--document-id",
        help="Exact Onshape document identifier to read.",
    ),
    json_output: bool = typer.Option(
        True,
        "--json/--text",
        help="Emit a machine-readable safe receipt (default: JSON).",
    ),
) -> None:
    """Read one explicitly selected document and print its safe receipt."""

    receipt = LiveService().read_document(document_id)
    _emit_receipt(receipt, json_output=json_output)
    _exit_for_receipt(receipt)


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
