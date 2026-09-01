"""Explicit, read-only application services for live Onshape checks.

The service is intentionally opt-in.  Constructing the service does not start
an MCP process, inspect credential contents, or perform network I/O.  A
session is opened only when one of the explicit live methods is called.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Protocol

from .contracts import OnshapeScope, StrictModel, TransportReceipt
from .live_transport import OnshapeMcpReadTransport
from .mcp_stdio import McpStdioSession, McpTransportError

LIVE_MCP_COMMAND = ("npx.cmd", "--yes", "onshape-mcp@0.5.2")
DEFAULT_MCP_TIMEOUT_SECONDS = 10.0


class LocalAuthStatus(StrictModel):
    """Secret-free local presence information for the upstream MCP."""

    status: Literal["READY_LOCAL", "AUTH_REQUIRED", "NOT_CONFIGURED"]
    configured: bool
    authenticated: bool
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


def _default_config_root() -> Path:
    configured_root = os.environ.get("ONSHAPE_MCP_CONFIG_DIR")
    if configured_root and configured_root.strip():
        return Path(configured_root)

    appdata = os.environ.get("APPDATA")
    if appdata and appdata.strip():
        return Path(appdata) / "onshape-mcp"

    if os.name == "nt":
        return Path.home() / "AppData" / "Roaming" / "onshape-mcp"
    return Path.home() / ".config" / "onshape-mcp"


def _presence(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _tokens_present(config_root: Path) -> bool:
    """Detect token-file presence by names only; never inspect file contents."""

    known_names = (
        "tokens.json",
        "token.json",
        ".tokens.json",
        ".token.json",
        "tokens.toml",
        "token.toml",
        "tokens",
        "token",
    )
    for name in known_names:
        if _presence(config_root / name):
            return True

    try:
        children = config_root.iterdir()
    except OSError:
        return False
    try:
        for child in children:
            if child.is_file() and "token" in child.name.lower():
                return True
    except OSError:
        return False
    return False


def inspect_local_auth(
    config_root: Path | str | None = None,
) -> LocalAuthStatus:
    """Return local config/token presence without reading either file."""

    root = Path(config_root) if config_root is not None else _default_config_root()
    config_present = _presence(root / "config.toml")
    tokens_present = _tokens_present(root)
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
        authenticated=tokens_present,
        config_present=config_present,
        tokens_present=tokens_present,
    )


class LiveService:
    """Perform explicit authentication and bounded read-only live operations."""

    def __init__(self, *, session_factory: SessionFactory | None = None) -> None:
        # Resolve the module function at construction time so tests and callers
        # can inject a deterministic fake by replacing ``open_session``.
        self._session_factory = session_factory or open_session

    def auth_status(self) -> TransportReceipt:
        """Validate the existing login through ``validate=true``."""

        return self._run(
            "auth_status",
            OnshapeScope(),
            lambda transport: transport.auth_status(),
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
            lambda transport: transport.read("list_documents", {"limit": limit}),
        )

    def read_document(self, document_id: str) -> TransportReceipt:
        """Read one approved document metadata response by exact document ID."""

        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id must be a non-empty string")
        scope = OnshapeScope(document_id=document_id)
        return self._run(
            "get_document",
            scope,
            lambda transport: transport.read("get_document", {}),
        )

    def _run(
        self,
        operation: str,
        scope: OnshapeScope,
        action: Callable[[OnshapeMcpReadTransport], TransportReceipt],
    ) -> TransportReceipt:
        try:
            with self._managed_session() as session:
                transport = OnshapeMcpReadTransport(session, scope)
                return action(transport)
        except Exception as error:
            return _failed_receipt(operation, error)

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
