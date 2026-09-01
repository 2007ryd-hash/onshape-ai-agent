"""Allowlisted, read-only transport for the local Onshape MCP server.

The transport deliberately exposes semantic operations instead of forwarding
arbitrary MCP arguments.  Every request is assembled from the approved
``OnshapeScope`` and a small set of bounded, operation-specific parameters.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Protocol

from .contracts import OnshapeScope, TransportReceipt
from .mcp_stdio import McpTransportError


class _ToolSession(Protocol):
    def call_tool(self, tool_name: str, arguments: Mapping[str, object]) -> object: ...


class LivePolicyDenied(Exception):
    """A live operation was rejected before the MCP session was called."""

    def __init__(self, code: str, reason: str = "") -> None:
        self.code = code
        self.reason = reason
        super().__init__(code)


class LiveTransportError(McpTransportError):
    """A live request failed with a stable, body-free public error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)


EXPECTED_ENDPOINTS: dict[str, str] = {
    "list_documents": "getDocuments",
    "get_document": "getDocument",
    "list_workspaces": "getDocumentWorkspaces",
    "read_elements": "getElementsInDocument",
    "body_details": "getPartStudioBodyDetails",
    "bounding_boxes": "getPartStudioBoundingBoxes",
    "mass_properties": "getPartStudioMassProperties",
}

_DOCUMENT_OPERATIONS = frozenset(
    {
        "get_document",
        "list_workspaces",
        "read_elements",
        "body_details",
        "bounding_boxes",
        "mass_properties",
    }
)
_VERSIONED_OPERATIONS = frozenset(
    {"read_elements", "body_details", "bounding_boxes", "mass_properties"}
)
_BODY_OPERATIONS = frozenset({"body_details", "bounding_boxes", "mass_properties"})

_ALLOWED_PARAMETERS: dict[str, frozenset[str]] = {
    "list_documents": frozenset({"limit"}),
    "get_document": frozenset({"document_id"}),
    "list_workspaces": frozenset({"document_id"}),
    "read_elements": frozenset({"document_id", "wvm", "wvm_id"}),
    "body_details": frozenset({"document_id", "wvm", "wvm_id", "element_id"}),
    "bounding_boxes": frozenset({"document_id", "wvm", "wvm_id", "element_id"}),
    "mass_properties": frozenset({"document_id", "wvm", "wvm_id", "element_id"}),
}

_FORBIDDEN_KEY_NAMES = frozenset(
    {
        "endpoint",
        "url",
        "method",
        "body",
        "headerparams",
        "headers",
        "filerefs",
        "auth",
        "login",
        "authlogin",
        "authorization",
    }
)
_STATUS_CODES = {
    401: "AUTH_REQUIRED",
    403: "SCOPE_DENIED",
    404: "NOT_FOUND",
    429: "RATE_LIMITED",
}
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
    }
)
_CODE_KEY_NAMES = frozenset(
    {"code", "errorcode", "status", "statuscode", "httpstatus", "httpstatuscode"}
)
_STATUS_KEY_NAMES = frozenset({"status", "statuscode", "httpstatus", "httpstatuscode"})
_ERROR_CONTAINER_NAMES = frozenset({"error", "errors", "exception", "failure"})
_HTTP_STATUS_TEXT = {
    "unauthorized": "AUTH_REQUIRED",
    "forbidden": "SCOPE_DENIED",
    "notfound": "NOT_FOUND",
    "ratelimited": "RATE_LIMITED",
    "toomanyrequests": "RATE_LIMITED",
}


class OnshapeMcpReadTransport:
    """Route approved semantic reads through a bounded MCP session."""

    sends_network = True
    transport_name = "onshape-mcp-stdio"

    def __init__(self, session: _ToolSession, scope: OnshapeScope) -> None:
        if not isinstance(scope, OnshapeScope):
            raise LivePolicyDenied("SCOPE_DENIED")
        self._session = session
        self._scope = scope
        self._last_response: object | None = None

    def auth_status(self) -> TransportReceipt:
        """Validate the existing local MCP authentication state."""

        self._validate_scope("auth_status")
        try:
            response = self._session.call_tool(
                "onshape_auth_status", {"validate": True}
            )
        except Exception as error:
            raise self._map_session_error(error) from None

        response = self._validate_response(response)
        self._last_response = response
        return TransportReceipt(
            operation="auth_status",
            status="SUCCEEDED",
            network_request_sent=True,
            readback_verified=True,
            evidence_summary={"response_present": True},
        )

    def read(
        self,
        operation: str,
        safe_parameters: Mapping[str, object] | None = None,
    ) -> TransportReceipt:
        """Execute one fixed read operation and return only a safe receipt."""

        if operation not in EXPECTED_ENDPOINTS:
            raise LivePolicyDenied("OPERATION_DENIED")
        self._validate_scope(operation)
        parameters = self._validate_parameters(operation, safe_parameters)
        arguments = self._build_arguments(operation, parameters)

        try:
            response = self._session.call_tool("onshape_api_call", arguments)
        except Exception as error:
            raise self._map_session_error(error) from None

        response = self._validate_response(response)
        self._last_response = response
        if operation == "get_document":
            self._verify_document_id(response)
            evidence = {"document_id_matches": True}
        else:
            evidence = {"response_present": True}
        return TransportReceipt(
            operation=operation,
            status="SUCCEEDED",
            network_request_sent=True,
            readback_verified=True,
            evidence_summary=evidence,
        )

    def _validate_scope(self, operation: str) -> None:
        scope = self._scope
        if scope.stack != "cad.onshape.com":
            raise LivePolicyDenied("SCOPE_DENIED")
        if scope.wvm not in {None, "w", "v", "m"}:
            raise LivePolicyDenied("SCOPE_DENIED")
        if (scope.wvm is None) != (scope.wvm_id is None):
            raise LivePolicyDenied("SCOPE_DENIED")
        if operation == "auth_status" or operation == "list_documents":
            return
        if operation in _DOCUMENT_OPERATIONS and not scope.document_id:
            raise LivePolicyDenied("SCOPE_DENIED")
        if operation in _VERSIONED_OPERATIONS and (
            scope.wvm is None or scope.wvm_id is None
        ):
            raise LivePolicyDenied("SCOPE_DENIED")
        if operation in _BODY_OPERATIONS and not scope.element_id:
            raise LivePolicyDenied("SCOPE_DENIED")

    def _validate_parameters(
        self,
        operation: str,
        safe_parameters: Mapping[str, object] | None,
    ) -> dict[str, object]:
        if safe_parameters is None:
            parameters: Mapping[str, object] = {}
        elif isinstance(safe_parameters, Mapping):
            parameters = safe_parameters
        else:
            raise LivePolicyDenied("INVALID_PARAMETERS")

        if self._contains_forbidden_key(parameters):
            raise LivePolicyDenied("OPERATION_DENIED")

        allowed = _ALLOWED_PARAMETERS[operation]
        for key in parameters:
            if not isinstance(key, str) or key not in allowed:
                raise LivePolicyDenied("INVALID_PARAMETERS")

        self._validate_scope_identifiers(parameters)
        if operation == "list_documents" and "limit" in parameters:
            limit = parameters["limit"]
            if (
                isinstance(limit, bool)
                or not isinstance(limit, int)
                or not 1 <= limit <= 100
            ):
                raise LivePolicyDenied("INVALID_PARAMETERS")
        return dict(parameters)

    def _validate_scope_identifiers(self, parameters: Mapping[str, object]) -> None:
        expected = {
            "document_id": self._scope.document_id,
            "wvm": self._scope.wvm,
            "wvm_id": self._scope.wvm_id,
            "element_id": self._scope.element_id,
        }
        for name, supplied in parameters.items():
            if name not in expected:
                continue
            if not isinstance(supplied, str) or supplied != expected[name]:
                raise LivePolicyDenied("SCOPE_DENIED")

    @staticmethod
    def _contains_forbidden_key(
        value: object, *, _seen: set[int] | None = None
    ) -> bool:
        if _seen is None:
            _seen = set()
        if isinstance(value, Mapping):
            marker = id(value)
            if marker in _seen:
                return True
            _seen.add(marker)
            for key, nested in value.items():
                if isinstance(key, str) and _normalise_key(key) in _FORBIDDEN_KEY_NAMES:
                    return True
                if OnshapeMcpReadTransport._contains_forbidden_key(nested, _seen=_seen):
                    return True
            return False
        if isinstance(value, (list, tuple, set, frozenset)):
            marker = id(value)
            if marker in _seen:
                return True
            _seen.add(marker)
            return any(
                OnshapeMcpReadTransport._contains_forbidden_key(item, _seen=_seen)
                for item in value
            )
        return False

    def _build_arguments(
        self, operation: str, parameters: Mapping[str, object]
    ) -> dict[str, object]:
        arguments: dict[str, object] = {"endpoint": EXPECTED_ENDPOINTS[operation]}
        path_params: dict[str, str] = {}
        scope = self._scope
        if operation != "list_documents":
            assert scope.document_id is not None
            path_params["did"] = scope.document_id
        if operation in _VERSIONED_OPERATIONS:
            assert scope.wvm is not None and scope.wvm_id is not None
            path_params["wvm"] = scope.wvm
            path_params["wvmid"] = scope.wvm_id
        if operation in _BODY_OPERATIONS:
            assert scope.element_id is not None
            path_params["eid"] = scope.element_id
        if path_params:
            arguments["path_params"] = path_params
        if operation == "list_documents" and "limit" in parameters:
            arguments["query_params"] = {"limit": str(parameters["limit"])}
        return arguments

    @staticmethod
    def _validate_response(response: object) -> Mapping[str, Any] | list[Any]:
        status_error = _status_error_code(response)
        if status_error is not None:
            raise LiveTransportError(status_error)
        if not isinstance(response, (Mapping, list)):
            raise LiveTransportError("INVALID_RESPONSE")
        if isinstance(response, Mapping) and _contains_error_marker(response):
            raise LiveTransportError("INVALID_RESPONSE")
        return response

    def _verify_document_id(self, response: Mapping[str, Any] | list[Any]) -> None:
        if not isinstance(response, Mapping):
            raise LiveTransportError("VERIFICATION_FAILED")
        returned_id = _find_document_id(response)
        if returned_id != self._scope.document_id:
            raise LiveTransportError("VERIFICATION_FAILED")

    @staticmethod
    def _map_session_error(error: Exception) -> LiveTransportError:
        if isinstance(error, LiveTransportError):
            return error
        code = getattr(error, "code", None)
        if isinstance(code, str):
            mapped = _map_stable_error_code(code)
            if mapped is not None:
                return LiveTransportError(mapped)
        status_code = _status_error_code(error)
        if status_code is not None:
            return LiveTransportError(status_code)
        return LiveTransportError("TRANSPORT_FAILED")


def _normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _map_stable_error_code(code: str) -> str | None:
    normalised = _normalise_key(code)
    aliases = {
        "authrequired": "AUTH_REQUIRED",
        "unauthorized": "AUTH_REQUIRED",
        "scopedenied": "SCOPE_DENIED",
        "forbidden": "SCOPE_DENIED",
        "notfound": "NOT_FOUND",
        "ratelimited": "RATE_LIMITED",
        "transportunavailable": "TRANSPORT_UNAVAILABLE",
        "transporttimeout": "TRANSPORT_TIMEOUT",
        "transportfailed": "TRANSPORT_FAILED",
        "responsetoolarge": "RESPONSE_TOO_LARGE",
        "responsequeuefull": "RESPONSE_QUEUE_FULL",
        "invalidresponse": "INVALID_RESPONSE",
        "verificationfailed": "VERIFICATION_FAILED",
    }
    mapped = aliases.get(normalised)
    if mapped is not None:
        return mapped
    if code in _STABLE_ERROR_CODES:
        return code
    return None


def _status_error_code(value: object) -> str | None:
    """Extract only a known HTTP/API error code without serialising the value."""

    seen: set[int] = set()

    def visit(current: object, *, in_error: bool = False, depth: int = 0) -> str | None:
        if depth > 8:
            return None
        if isinstance(current, Mapping):
            marker = id(current)
            if marker in seen:
                return None
            seen.add(marker)
            for raw_key, nested in current.items():
                if not isinstance(raw_key, str):
                    continue
                key = _normalise_key(raw_key)
                if key in _STATUS_KEY_NAMES:
                    mapped = _status_value(nested)
                    if mapped is not None:
                        return mapped
                if key in _CODE_KEY_NAMES or key in _ERROR_CONTAINER_NAMES:
                    mapped = visit(nested, in_error=True, depth=depth + 1)
                    if mapped is not None:
                        return mapped
                elif isinstance(nested, (Mapping, list, tuple)) and (
                    in_error or key in _ERROR_CONTAINER_NAMES
                ):
                    mapped = visit(nested, in_error=True, depth=depth + 1)
                    if mapped is not None:
                        return mapped
            return None
        if isinstance(current, (list, tuple)):
            for nested in current:
                mapped = visit(nested, in_error=in_error, depth=depth + 1)
                if mapped is not None:
                    return mapped
            return None
        if in_error:
            return _status_value(current)
        return None

    return visit(value)


def _status_value(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return _STATUS_CODES.get(value)
    if isinstance(value, str):
        mapped = _map_stable_error_code(value)
        if mapped in {
            "AUTH_REQUIRED",
            "SCOPE_DENIED",
            "NOT_FOUND",
            "RATE_LIMITED",
        }:
            return mapped
        compact = _normalise_key(value)
        if compact in _HTTP_STATUS_TEXT:
            return _HTTP_STATUS_TEXT[compact]
        match = re.search(r"\b(401|403|404|429)\b", value)
        if match:
            return _STATUS_CODES[int(match.group(1))]
    return None


def _contains_error_marker(
    value: Mapping[str, Any], *, _seen: set[int] | None = None
) -> bool:
    if _seen is None:
        _seen = set()
    marker = id(value)
    if marker in _seen:
        return True
    _seen.add(marker)
    for raw_key, nested in value.items():
        if not isinstance(raw_key, str):
            continue
        key = _normalise_key(raw_key)
        if key in _ERROR_CONTAINER_NAMES:
            return True
        if isinstance(nested, Mapping) and _contains_error_marker(nested, _seen=_seen):
            return True
        if isinstance(nested, list) and any(
            isinstance(item, Mapping) and _contains_error_marker(item, _seen=_seen)
            for item in nested
        ):
            return True
    return False


def _find_document_id(
    value: Mapping[str, Any], *, _seen: set[int] | None = None
) -> str | None:
    if _seen is None:
        _seen = set()
    marker = id(value)
    if marker in _seen:
        return None
    _seen.add(marker)
    direct_id = value.get("id")
    if isinstance(direct_id, str):
        return direct_id
    document_id = value.get("documentId")
    if isinstance(document_id, str):
        return document_id
    for key in ("document", "data", "response"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            found = _find_document_id(nested, _seen=_seen)
            if found is not None:
                return found
    return None
