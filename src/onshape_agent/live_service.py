"""Explicit, read-only application services for live Onshape checks.

The service is intentionally opt-in.  Constructing the service does not start
an MCP process, inspect credential contents, or perform network I/O.  A
session is opened only when one of the explicit live methods is called.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from .contracts import (
    ArtifactType,
    CadAction,
    ExecutionMode,
    ExecutionPlan,
    GatewayReport,
    OnshapeScope,
    RunState,
    StrictModel,
    TransportReceipt,
)
from .gateway import CadGateway
from .live_transport import OnshapeMcpReadTransport
from .mcp_stdio import McpStdioSession, McpTransportError
from .runlog import RunLog

LIVE_MCP_COMMAND = ("npx.cmd", "--yes", "onshape-mcp@0.5.2")
DEFAULT_MCP_TIMEOUT_SECONDS = 10.0


class LocalAuthStatus(StrictModel):
    """Secret-free local presence information for the upstream MCP."""

    status: Literal["READY_LOCAL", "AUTH_REQUIRED", "NOT_CONFIGURED"]
    configured: bool
    authenticated: None = None
    verification: Literal["unverified"] = "unverified"
    config_present: bool
    tokens_present: bool
    network_request_sent: Literal[False] = False
    credential_values_read: Literal[False] = False


class _SessionLike(Protocol):
    def call_tool(self, tool_name: str, arguments: dict[str, object]) -> object: ...


SessionFactory = Callable[[], object]


def open_session(
    *,
    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS,
) -> McpStdioSession:
    """Construct the pinned local MCP session without entering it."""

    return McpStdioSession(list(LIVE_MCP_COMMAND), timeout_seconds=timeout_seconds)


def _default_root(*, data: bool) -> Path:
    # Mirrors onshape-mcp v0.5.2 config.rs / oauth.rs: absolute XDG
    # overrides take precedence even on Windows; relative ones are ignored.
    xdg = os.environ.get("XDG_DATA_HOME" if data else "XDG_CONFIG_HOME")
    if xdg and Path(xdg).is_absolute():
        base = Path(xdg)
    elif sys.platform == "win32":
        value = os.environ.get("LOCALAPPDATA" if data else "APPDATA")
        base = (
            Path(value)
            if value
            else Path.home() / "AppData" / ("Local" if data else "Roaming")
        )
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / (".local/share" if data else ".config")
    return base / "onshape-mcp"


def _presence(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def inspect_local_auth(
    config_root: Path | str | None = None,
    *,
    data_root: Path | str | None = None,
) -> LocalAuthStatus:
    """Return presence only; authentication always remains unverified.

    Explicit roots (and the legacy local-inspection override) support isolated
    diagnostics. They do not configure the upstream process.
    """

    override = config_root or os.environ.get("ONSHAPE_MCP_CONFIG_DIR")
    root = Path(override) if override else _default_root(data=False)
    token_root = (
        Path(data_root)
        if data_root is not None
        else (Path(override) if override else _default_root(data=True))
    )
    config_present = _presence(root / "config.toml")
    tokens_present = _presence(token_root / "tokens.json")
    if config_present and tokens_present:
        status: Literal["READY_LOCAL", "AUTH_REQUIRED", "NOT_CONFIGURED"] = (
            "READY_LOCAL"
        )
    elif config_present or tokens_present:
        status = "AUTH_REQUIRED"
    else:
        status = "NOT_CONFIGURED"
    return LocalAuthStatus(
        status=status,
        configured=config_present,
        config_present=config_present,
        tokens_present=tokens_present,
    )


class LiveService:
    """Perform explicit authentication and bounded read-only live operations."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        output_root: Path = Path("runs"),
    ) -> None:
        # Resolve the module function at construction time so tests and callers
        # can inject a deterministic fake by replacing ``open_session``.
        self._session_factory = session_factory or open_session
        self._output_root = Path(output_root)

    def auth_status(self) -> TransportReceipt:
        """Validate the existing login through ``validate=true``."""

        return self._run(
            "auth_status",
            OnshapeScope(),
            {},
        )

    def list_documents(self, limit: int = 1) -> TransportReceipt:
        """List at most 100 documents and return only a safe receipt."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit must be an integer between 1 and 100")
        return self._run(
            "list_documents",
            OnshapeScope(),
            {"limit": limit},
        )

    def read_document(self, document_id: str) -> TransportReceipt:
        """Read one approved document metadata response by exact document ID."""

        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id must be a non-empty string")
        scope = OnshapeScope(document_id=document_id)
        return self._run(
            "get_document",
            scope,
            {},
        )

    def _run(
        self,
        operation: str,
        scope: OnshapeScope,
        parameters: dict[str, object],
    ) -> TransportReceipt:
        run_id = f"live_{uuid4().hex}"
        log = RunLog(self._output_root, run_id=run_id)
        plan = ExecutionPlan(
            plan_id=run_id,
            approved_design_hash="read-only-command",
            target_scope="onshape",
            execution_mode=ExecutionMode.LIVE,
            onshape_scope=scope,
            actions=[
                CadAction(
                    action_id="read",
                    type="read_back",
                    semantic_id=operation,
                    parameters={"read_kind": operation, **parameters},
                )
            ],
        )
        report: GatewayReport | None = None
        try:
            with self._managed_session() as session:
                transport = OnshapeMcpReadTransport(session, scope)
                report = CadGateway(transport).execute(plan)
                if report.status == "EXECUTED":
                    receipt = report.receipts[0]
                else:
                    receipt = TransportReceipt(
                        operation=operation,
                        status="FAILED",
                        network_request_sent=report.network_request_sent,
                        readback_verified=False,
                        error_code=report.code,
                    )
        except Exception as error:
            receipt = _failed_receipt(operation, error)
            if report is not None and report.network_request_sent:
                receipt = receipt.model_copy(update={"network_request_sent": True})
            report = None
        reference = log.write_artifact(
            artifact_id="live_execution_report",
            artifact_type=ArtifactType.EXECUTION_REPORT,
            producer="live_service",
            payload=(
                report.model_dump(mode="json")
                if report
                else {"receipt": receipt.model_dump(mode="json")}
            ),
        )
        log.create_manifest(
            main_model="not_used",
            reasoning_effort="not_used",
            execution_metadata={
                "execution_mode": "live",
                "transport_name": "onshape-mcp-stdio",
                "operation": operation,
                "status": receipt.status,
                "network_request_sent": receipt.network_request_sent,
                "readback_verified": receipt.readback_verified,
                "artifacts": [reference.model_dump(mode="json")],
            },
        )
        log.append_event(
            actor="live_service",
            stage=RunState.CAD_EXECUTION,
            event="LIVE_OPERATION_COMPLETED",
            details=receipt.model_dump(mode="json"),
        )
        return receipt

    @contextmanager
    def _managed_session(self) -> Iterator[_SessionLike]:
        resource = self._session_factory()
        enter = getattr(resource, "__enter__", None)
        exit_method = getattr(resource, "__exit__", None)
        if callable(enter) and callable(exit_method):
            with resource as session:
                yield session
            return

        try:
            yield resource  # type: ignore[misc]
        finally:
            close = getattr(resource, "close", None)
            if callable(close):
                close()


_STABLE_ERROR_CODES = frozenset(
    {
        "AUTH_REQUIRED",
        "SCOPE_DENIED",
        "NOT_FOUND",
        "RATE_LIMITED",
        "INVALID_RESPONSE",
        "TRANSPORT_UNAVAILABLE",
        "TRANSPORT_TIMEOUT",
        "TRANSPORT_FAILED",
        "RESPONSE_TOO_LARGE",
        "RESPONSE_QUEUE_FULL",
        "VERIFICATION_FAILED",
    }
)


def _failed_receipt(operation: str, error: Exception) -> TransportReceipt:
    code = getattr(error, "code", None)
    if not isinstance(code, str) or code not in _STABLE_ERROR_CODES:
        if isinstance(error, (FileNotFoundError, PermissionError, OSError)):
            code = "TRANSPORT_UNAVAILABLE"
        elif isinstance(error, ValueError):
            code = "INVALID_RESPONSE"
        elif isinstance(error, McpTransportError):
            code = "TRANSPORT_FAILED"
        else:
            code = "TRANSPORT_FAILED"
    return TransportReceipt(
        operation=operation,
        status="FAILED",
        network_request_sent=bool(getattr(error, "network_request_sent", False)),
        readback_verified=False,
        error_code=code,
    )
