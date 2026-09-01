"""Allowlisted, read-only transport for the local Onshape MCP server.

The transport deliberately exposes semantic operations instead of forwarding
arbitrary MCP arguments.  Every request is assembled from the approved
``OnshapeScope`` and a small set of bounded, operation-specific parameters.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType
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


_EXPECTED_ENDPOINTS: Mapping[str, str] = MappingProxyType(
    {
        "list_documents": "getDocuments",
        "get_document": "getDocument",
        "list_workspaces": "getDocumentWorkspaces",
        "read_elements": "getElementsInDocument",
        "body_details": "getPartStudioBodyDetails",
        "bounding_boxes": "getPartStudioBoundingBoxes",
        "mass_properties": "getPartStudioMassProperties",
    }
)

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
        "VERIFICATION_FAILED",
    }
)
_CODE_KEY_NAMES = frozenset(
    {"code", "errorcode", "status", "statuscode", "httpstatus", "httpstatuscode"}
)
_STATUS_KEY_NAMES = frozenset({"status", "statuscode", "httpstatus", "httpstatuscode"})
_ERROR_CONTAINER_NAMES = frozenset({"error", "errors", "exception", "failure"})
_ERROR_STATUS_VALUES = frozenset(
    {
        "error",
        "failed",
        "failure",
        "invalid",
        "expired",
        "unauthorized",
        "forbidden",
        "notfound",
        "ratelimited",
        "denied",
        "rejected",
        "timeout",
        "unavailable",
        "authrequired",
        "authenticationrequired",
        "authenticationfailed",
        "authfailed",
        "notauthenticated",
        "notloggedin",
        "unauthenticated",
        "loginrequired",
        "loginfailed",
        "tokenexpired",
        "sessionexpired",
    }
)
_AUTH_ERROR_MESSAGE_MARKERS = frozenset(
    {
        "authrequired",
        "authenticationrequired",
        "authenticationfailed",
        "authfailed",
        "unauthorized",
        "unauthenticated",
        "notauthenticated",
        "notloggedin",
        "loginrequired",
        "loginfailed",
        "tokenexpired",
        "tokenhasexpired",
        "sessionexpired",
        "credentialexpired",
        "invalidtoken",
        "tokeninvalid",
    }
)
_HTTP_STATUS_TEXT = {
    "unauthorized": "AUTH_REQUIRED",
    "forbidden": "SCOPE_DENIED",
    "notfound": "NOT_FOUND",
    "ratelimited": "RATE_LIMITED",
    "toomanyrequests": "RATE_LIMITED",
}
_AUTH_STATUS_SUCCESS_VALUES = frozenset(
    {"valid", "authenticated", "connected", "ready"}
)
_AUTH_STATUS_FAILURE_VALUES = frozenset(
    {
        "invalid",
        "expired",
        "notconfigured",
        "notvalidated",
        "notauthenticated",
        "notloggedin",
        "loggedout",
        "oauthpending",
        "unauthorized",
        "authrequired",
    }
)
_AUTH_FALSE_VALUES = frozenset(
    {
        "false",
        "0",
        "no",
        "off",
        "invalid",
        "expired",
        "unauthenticated",
        "notauthenticated",
        "notloggedin",
        "loggedout",
        "notconfigured",
        "notvalidated",
        "oauthpending",
        "unauthorized",
        "authrequired",
    }
)
_AUTH_TRUE_VALUES = frozenset(
    {"true", "1", "yes", "on", "valid", "authenticated", "connected", "ready"}
)
_AUTH_BOOLEAN_KEYS = frozenset({"authenticated", "configured", "valid"})
_LIST_READ_OPERATIONS = frozenset(
    {"list_documents", "list_workspaces", "read_elements"}
)
_LIST_CONTAINER_KEYS = frozenset({"items"})
_BOUNDS_KEYS = frozenset({"lowX", "lowY", "lowZ", "highX", "highY", "highZ"})


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
        auth_error = _auth_status_error_code(response)
        if auth_error is not None:
            raise LiveTransportError(auth_error)
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

        if operation not in _EXPECTED_ENDPOINTS:
            raise LivePolicyDenied("OPERATION_DENIED")
        self._validate_scope(operation)
        parameters = self._validate_parameters(operation, safe_parameters)
        arguments = self._build_arguments(operation, parameters)

        try:
            response = self._session.call_tool("onshape_api_call", arguments)
        except Exception as error:
            raise self._map_session_error(error) from None

        response = self._validate_response(response)
        if operation == "get_document":
            self._verify_document_id(response)
            evidence = {"document_id_matches": True}
        else:
            evidence = self._read_invariant(operation, response)
        self._last_response = response
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
        arguments: dict[str, object] = {"endpoint": _EXPECTED_ENDPOINTS[operation]}
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
        if _contains_error_marker(response):
            raise LiveTransportError("INVALID_RESPONSE")
        return response

    @staticmethod
    def _read_invariant(
        operation: str, response: Mapping[str, Any] | list[Any]
    ) -> dict[str, bool | int | float | str]:
        """Validate the smallest useful shape for each fixed read route."""

        if operation in _LIST_READ_OPERATIONS:
            items = _countable_items(operation, response)
            if items is None:
                raise LiveTransportError("INVALID_RESPONSE")
            return {"item_count": len(items)}

        if operation == "body_details":
            bodies = _non_empty_list_field(response, "bodies")
            if bodies is None:
                raise LiveTransportError("INVALID_RESPONSE")
            return {"body_count": len(bodies)}

        if operation == "bounding_boxes":
            if not isinstance(response, Mapping) or not _has_numeric_bounds(response):
                raise LiveTransportError("INVALID_RESPONSE")
            return {"bounds_present": True}

        if operation == "mass_properties":
            bodies = _non_empty_mapping_field(response, "bodies")
            if bodies is None:
                raise LiveTransportError("INVALID_RESPONSE")
            return {"body_count": len(bodies)}

        raise LiveTransportError("INVALID_RESPONSE")

    def _verify_document_id(self, response: Mapping[str, Any] | list[Any]) -> None:
        if not isinstance(response, Mapping) or not response:
            raise LiveTransportError("INVALID_RESPONSE")
        returned_id = _find_document_id(response)
        if returned_id is None:
            raise LiveTransportError("INVALID_RESPONSE")
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


def _auth_status_error_code(value: object) -> str | None:
    """Return a stable result for the explicit authentication state.

    The 0.5.x Onshape MCP reports ``status=valid``/``status=invalid`` while
    wrappers and older clients commonly expose boolean ``authenticated`` or
    ``valid`` fields.  A positive result is accepted only when one of those
    explicit signals is present.  Any explicit negative signal wins over a
    positive signal so a contradictory wrapper cannot be treated as logged in.
    """

    if _status_error_code(value) is not None:
        return _status_error_code(value)
    if not isinstance(value, Mapping) or not value:
        return "INVALID_RESPONSE"

    signals = _AuthSignals()
    _collect_auth_signals(value, signals)
    if signals.failure:
        return "AUTH_REQUIRED"
    if signals.success:
        return None
    return "INVALID_RESPONSE"


class _AuthSignals:
    """Internal accumulator for recursive authentication-state inspection."""

    def __init__(self) -> None:
        self.success = False
        self.failure = False


def _collect_auth_signals(
    value: object,
    signals: _AuthSignals,
    *,
    _seen: set[int] | None = None,
    _depth: int = 0,
) -> None:
    if _depth > 8:
        return
    if _seen is None:
        _seen = set()
    if isinstance(value, Mapping):
        marker = id(value)
        if marker in _seen:
            return
        _seen.add(marker)
        for raw_key, nested in value.items():
            if not isinstance(raw_key, str):
                continue
            key = _normalise_key(raw_key)
            if key == "status":
                _collect_auth_status_value(nested, signals)
            elif key in _AUTH_BOOLEAN_KEYS:
                state = _auth_flag_state(nested)
                if state is False:
                    signals.failure = True
                elif state is True and key != "configured":
                    signals.success = True
            if isinstance(nested, (Mapping, list, tuple)):
                _collect_auth_signals(
                    nested,
                    signals,
                    _seen=_seen,
                    _depth=_depth + 1,
                )
        return
    if isinstance(value, (list, tuple)):
        marker = id(value)
        if marker in _seen:
            return
        _seen.add(marker)
        for nested in value:
            _collect_auth_signals(
                nested,
                signals,
                _seen=_seen,
                _depth=_depth + 1,
            )


def _collect_auth_status_value(value: object, signals: _AuthSignals) -> None:
    if not isinstance(value, str):
        return
    state = _normalise_key(value)
    if state in _AUTH_STATUS_FAILURE_VALUES:
        signals.failure = True
    elif state in _AUTH_STATUS_SUCCESS_VALUES:
        signals.success = True


def _auth_flag_state(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return value == 1
    if isinstance(value, str):
        state = _normalise_key(value)
        if state in _AUTH_FALSE_VALUES:
            return False
        if state in _AUTH_TRUE_VALUES:
            return True
    return None


def _countable_items(
    operation: str, response: Mapping[str, Any] | list[Any]
) -> list[Any] | None:
    if isinstance(response, list):
        return response
    if not isinstance(response, Mapping):
        return None
    # ``items`` is the 0.5.x getDocuments container and a safe common wrapper
    # for the array-shaped workspace/element endpoints.
    for key in _LIST_CONTAINER_KEYS:
        items = response.get(key)
        if isinstance(items, list):
            return items
    return None


def _non_empty_list_field(
    response: Mapping[str, Any] | list[Any], key: str
) -> list[Any] | None:
    if not isinstance(response, Mapping):
        return None
    value = response.get(key)
    if isinstance(value, list) and value:
        return value
    return None


def _non_empty_mapping_field(
    response: Mapping[str, Any] | list[Any], key: str
) -> Mapping[str, Any] | None:
    if not isinstance(response, Mapping):
        return None
    value = response.get(key)
    if isinstance(value, Mapping) and value:
        return value
    return None


def _has_numeric_bounds(response: Mapping[str, Any]) -> bool:
    if not _BOUNDS_KEYS.issubset(response):
        return False
    for key in _BOUNDS_KEYS:
        value = response[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            if not isfinite(value):
                return False
        except (OverflowError, TypeError):
            return False
    return True


def _map_stable_error_code(code: str) -> str | None:
    normalised = _normalise_key(code)
    aliases = {
        "authrequired": "AUTH_REQUIRED",
        "authenticationrequired": "AUTH_REQUIRED",
        "authexpired": "AUTH_REQUIRED",
        "expired": "AUTH_REQUIRED",
        "loginrequired": "AUTH_REQUIRED",
        "notauthenticated": "AUTH_REQUIRED",
        "notloggedin": "AUTH_REQUIRED",
        "unauthorized": "AUTH_REQUIRED",
        "unauthenticated": "AUTH_REQUIRED",
        "tokenexpired": "AUTH_REQUIRED",
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
                elif in_error:
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
        if any(
            marker in compact
            for marker in (
                "expired",
                "authrequired",
                "authenticationrequired",
                "notauthenticated",
                "notloggedin",
                "unauthenticated",
                "loginrequired",
            )
        ):
            return "AUTH_REQUIRED"
        if compact in _HTTP_STATUS_TEXT:
            return _HTTP_STATUS_TEXT[compact]
        match = re.search(r"\b(401|403|404|429)\b", value)
        if match:
            return _STATUS_CODES[int(match.group(1))]
    return None


def _contains_error_marker(
    value: object,
    *,
    _seen: set[int] | None = None,
    _root: bool = True,
) -> bool:
    """Detect error-shaped response nodes without serialising their payload."""

    if _seen is None:
        _seen = set()
    marker = id(value)
    if marker in _seen:
        return True
    _seen.add(marker)
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            if not isinstance(raw_key, str):
                continue
            key = _normalise_key(raw_key)
            if key in _ERROR_CONTAINER_NAMES:
                return True
            if not _root and key == "status" and _is_error_status_value(nested):
                return True
            if not _root and key == "message" and _is_auth_error_message(nested):
                return True
            if isinstance(nested, (Mapping, list)) and _contains_error_marker(
                nested, _seen=_seen, _root=False
            ):
                return True
        return False
    if isinstance(value, list):
        return any(
            _contains_error_marker(item, _seen=_seen, _root=False) for item in value
        )
    return False


def _is_error_status_value(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value in _STATUS_CODES
    if not isinstance(value, str):
        return False
    compact = _normalise_key(value)
    if compact in _ERROR_STATUS_VALUES:
        return True
    return any(
        marker in compact
        for marker in (
            "expired",
            "authrequired",
            "authenticationrequired",
            "authenticationfailed",
            "notauthenticated",
            "notloggedin",
            "unauthenticated",
            "loginrequired",
            "tokenexpired",
        )
    )


def _is_auth_error_message(value: object) -> bool:
    if not isinstance(value, str):
        return False
    compact = _normalise_key(value)
    if compact in _AUTH_ERROR_MESSAGE_MARKERS:
        return True
    return any(marker in compact for marker in _AUTH_ERROR_MESSAGE_MARKERS)


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
