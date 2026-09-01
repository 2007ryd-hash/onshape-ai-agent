"""Deterministic, secret-free diagnostics for a local installation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

from .contracts import StrictModel
from .live_service import LiveService


class DoctorCheck(StrictModel):
    """The result of one installation diagnostic."""

    name: str
    status: Literal["PASS", "FAIL"]
    detail: str


class DoctorReport(StrictModel):
    """Machine-readable installation status."""

    status: Literal["READY_OFFLINE", "READY_LIVE", "AUTH_REQUIRED", "NOT_READY"]
    provider_api_key_required: Literal[False] = False
    onshape_transport: Literal["not_configured", "onshape-mcp-stdio"] = (
        "not_configured"
    )
    network_request_sent: bool = False
    readback_verified: bool = False
    error_code: str | None = None
    checks: list[DoctorCheck]


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return path.name


def _file_check(
    *, name: str, path: Path, repo_root: Path, parse_json: bool = False
) -> DoctorCheck:
    relative_path = _display_path(path, repo_root)
    if not path.is_file():
        return DoctorCheck(
            name=name,
            status="FAIL",
            detail=f"missing file: {relative_path}",
        )

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return DoctorCheck(
            name=name,
            status="FAIL",
            detail=f"file cannot be read: {relative_path}",
        )

    if not content.strip():
        return DoctorCheck(
            name=name,
            status="FAIL",
            detail=f"file is empty: {relative_path}",
        )

    if parse_json:
        try:
            value = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return DoctorCheck(
                name=name,
                status="FAIL",
                detail=f"invalid JSON: {relative_path}",
            )
        if not isinstance(value, dict):
            return DoctorCheck(
                name=name,
                status="FAIL",
                detail=f"JSON object required: {relative_path}",
            )

    return DoctorCheck(
        name=name,
        status="PASS",
        detail=f"found: {relative_path}",
    )


def _python_check() -> DoctorCheck:
    version = tuple(sys.version_info[:3])
    supported = version[:2] >= (3, 12)
    version_text = ".".join(str(part) for part in version)
    return DoctorCheck(
        name="python_version",
        status="PASS" if supported else "FAIL",
        detail=(
            f"Python {version_text} meets the >=3.12 requirement"
            if supported
            else f"Python {version_text} is below the >=3.12 requirement"
        ),
    )


def _package_import_check(repo_root: Path) -> DoctorCheck:
    package_init = repo_root / "src" / "onshape_agent" / "__init__.py"
    if not package_init.is_file():
        return DoctorCheck(
            name="package_import",
            status="FAIL",
            detail="missing file: src/onshape_agent/__init__.py",
        )

    try:
        result = subprocess.run(
            [sys.executable, "-c", "import onshape_agent"],
            cwd=repo_root,
            env={
                "PYTHONNOUSERSITE": "1",
                "PYTHONPATH": str(repo_root / "src"),
            },
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        result = None

    if result is None or result.returncode != 0:
        return DoctorCheck(
            name="package_import",
            status="FAIL",
            detail="onshape_agent package import failed",
        )
    return DoctorCheck(
        name="package_import",
        status="PASS",
        detail="onshape_agent package imported",
    )


def _output_check(output_root: Path) -> DoctorCheck:
    if output_root.exists() and not output_root.is_dir():
        return DoctorCheck(
            name="output_directory",
            status="FAIL",
            detail="output path is not a directory",
        )

    probe_directory = output_root
    while not probe_directory.exists() and probe_directory != probe_directory.parent:
        probe_directory = probe_directory.parent

    if not probe_directory.is_dir():
        return DoctorCheck(
            name="output_directory",
            status="FAIL",
            detail="output directory has no existing directory parent",
        )

    try:
        with tempfile.NamedTemporaryFile(
            dir=probe_directory,
            prefix=".onshape-agent-doctor-",
            delete=True,
        ):
            pass
    except OSError:
        return DoctorCheck(
            name="output_directory",
            status="FAIL",
            detail="output directory is not writable",
        )

    detail = (
        "output directory is writable"
        if output_root.exists()
        else "output directory parent is writable"
    )
    return DoctorCheck(name="output_directory", status="PASS", detail=detail)


def _transport_check(*, live: bool = False) -> DoctorCheck:
    if live:
        return DoctorCheck(
            name="onshape_transport",
            status="PASS",
            detail="pinned onshape-mcp stdio transport selected explicitly",
        )
    return DoctorCheck(
        name="onshape_transport",
        status="PASS",
        detail="not_configured; offline mode is supported",
    )


def inspect_installation(
    repo_root: Path | str,
    *,
    output_root: Path | str | None = None,
    live: bool = False,
    live_service: LiveService | None = None,
) -> DoctorReport:
    """Inspect the local installation, optionally probing an explicit live session.

    The default path remains entirely offline.  ``live=True`` is the only path
    that constructs a session and asks the upstream MCP to validate auth.
    """

    root = Path(repo_root)
    output = Path(output_root) if output_root is not None else root / "runs"
    plugin_root = root / "plugins" / "onshape-engineering-agent"
    skill_root = plugin_root / "skills" / "onshape-engineering"

    checks = [
        _python_check(),
        _package_import_check(root),
        _file_check(
            name="codex_manifest",
            path=plugin_root / ".codex-plugin" / "plugin.json",
            repo_root=root,
            parse_json=True,
        ),
        _file_check(
            name="claude_manifest",
            path=plugin_root / ".claude-plugin" / "plugin.json",
            repo_root=root,
            parse_json=True,
        ),
        _file_check(
            name="shared_skill",
            path=skill_root / "SKILL.md",
            repo_root=root,
        ),
        _file_check(
            name="simple_bracket_request",
            path=root / "examples" / "simple-bracket" / "request.json",
            repo_root=root,
            parse_json=True,
        ),
        _output_check(output),
        _transport_check(live=live),
    ]
    offline_ready = all(check.status == "PASS" for check in checks)
    if not live:
        status = "READY_OFFLINE" if offline_ready else "NOT_READY"
        return DoctorReport(status=status, checks=checks)

    if not offline_ready:
        return DoctorReport(status="NOT_READY", checks=checks)

    service = live_service if live_service is not None else LiveService()
    receipt = service.auth_status()
    checks.append(
        DoctorCheck(
            name="onshape_auth_status",
            status="PASS" if receipt.status == "SUCCEEDED" else "FAIL",
            detail=(
                "validated existing Onshape authentication"
                if receipt.status == "SUCCEEDED"
                else (
                    "live authentication check failed: "
                    f"{receipt.error_code or 'UNKNOWN'}"
                )
            ),
        )
    )
    if (
        receipt.status == "SUCCEEDED"
        and receipt.network_request_sent
        and receipt.readback_verified
    ):
        status = "READY_LIVE"
    elif receipt.error_code == "AUTH_REQUIRED":
        status = "AUTH_REQUIRED"
    else:
        status = "NOT_READY"
    return DoctorReport(
        status=status,
        onshape_transport="onshape-mcp-stdio",
        network_request_sent=receipt.network_request_sent,
        readback_verified=receipt.readback_verified,
        error_code=receipt.error_code,
        checks=checks,
    )
