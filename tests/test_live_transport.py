from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from onshape_agent.contracts import OnshapeScope, TransportReceipt
from onshape_agent.live_transport import (
    LivePolicyDenied,
    LiveTransportError,
    OnshapeMcpReadTransport,
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, object]


class FakeSession:
    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[ToolCall] = []

    @property
    def last_call(self) -> ToolCall:
        return self.calls[-1]

    def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append(ToolCall(name, arguments))
        response = self.responses.get(name)
        if callable(response):
            return response(name, arguments)
        return response


@pytest.fixture
def scoped_scope() -> OnshapeScope:
    return OnshapeScope(
        document_id="doc-123",
        wvm="w",
        wvm_id="workspace-456",
        element_id="element-789",
    )


@pytest.fixture
def documentless_scope() -> OnshapeScope:
    return OnshapeScope()


def test_auth_status_forces_validation_and_returns_safe_receipt() -> None:
    session = FakeSession({"onshape_auth_status": {"authenticated": True}})

    receipt = OnshapeMcpReadTransport(session, OnshapeScope()).auth_status()

    assert session.last_call == ToolCall("onshape_auth_status", {"validate": True})
    assert isinstance(receipt, TransportReceipt)
    assert receipt.operation == "auth_status"
    assert receipt.status == "SUCCEEDED"
    assert receipt.network_request_sent is True
    assert receipt.readback_verified is True
    assert receipt.evidence_summary == {"response_present": True}


@pytest.mark.parametrize(
    "response",
    [
        {"authenticated": False},
        {"configured": False},
        {"valid": False},
        {"status": "invalid"},
        {"status": "expired"},
        {"status": "not_configured"},
        {"status": "not_validated"},
        {"status": "not_authenticated"},
        {"status": "oauth_pending"},
        {"authenticated": "false"},
    ],
)
def test_auth_status_maps_explicitly_logged_out_shapes_to_auth_required(
    response: object,
) -> None:
    session = FakeSession({"onshape_auth_status": response})

    with pytest.raises(LiveTransportError, match="AUTH_REQUIRED") as raised:
        OnshapeMcpReadTransport(session, OnshapeScope()).auth_status()

    assert "secret" not in str(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        {"status": "valid", "auth_method": "oauth"},
        {"authenticated": True},
        {"valid": True},
    ],
)
def test_auth_status_accepts_only_explicit_success_shapes(response: object) -> None:
    session = FakeSession({"onshape_auth_status": response})

    receipt = OnshapeMcpReadTransport(session, OnshapeScope()).auth_status()

    assert receipt.status == "SUCCEEDED"
    assert receipt.readback_verified is True


def test_auth_status_does_not_treat_configuration_alone_as_auth_success() -> None:
    session = FakeSession({"onshape_auth_status": {"configured": True}})

    with pytest.raises(LiveTransportError, match="INVALID_RESPONSE"):
        OnshapeMcpReadTransport(session, OnshapeScope()).auth_status()


@pytest.mark.parametrize(
    ("operation", "endpoint", "expected_path"),
    [
        ("get_document", "getDocument", {"did": "doc-123"}),
        (
            "list_workspaces",
            "getDocumentWorkspaces",
            {"did": "doc-123"},
        ),
        (
            "read_elements",
            "getElementsInDocument",
            {"did": "doc-123", "wvm": "w", "wvmid": "workspace-456"},
        ),
        (
            "body_details",
            "getPartStudioBodyDetails",
            {
                "did": "doc-123",
                "wvm": "w",
                "wvmid": "workspace-456",
                "eid": "element-789",
            },
        ),
        (
            "bounding_boxes",
            "getPartStudioBoundingBoxes",
            {
                "did": "doc-123",
                "wvm": "w",
                "wvmid": "workspace-456",
                "eid": "element-789",
            },
        ),
        (
            "mass_properties",
            "getPartStudioMassProperties",
            {
                "did": "doc-123",
                "wvm": "w",
                "wvmid": "workspace-456",
                "eid": "element-789",
            },
        ),
    ],
)
def test_document_reads_use_fixed_endpoints_and_scope(
    operation: str,
    endpoint: str,
    expected_path: dict[str, str],
    scoped_scope: OnshapeScope,
) -> None:
    responses: dict[str, object] = {
        "get_document": {"id": "doc-123"},
        "list_workspaces": {"items": [{"id": "workspace-456"}]},
        "read_elements": {"items": [{"id": "element-789"}]},
        "body_details": {"bodies": [{"id": "body-1"}]},
        "bounding_boxes": {
            "lowX": 0.0,
            "lowY": 0.0,
            "lowZ": 0.0,
            "highX": 1.0,
            "highY": 1.0,
            "highZ": 1.0,
        },
        "mass_properties": {"bodies": {"body-1": {}}},
    }
    session = FakeSession({"onshape_api_call": responses[operation]})

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read(operation, {})

    assert session.last_call == ToolCall(
        "onshape_api_call",
        {"endpoint": endpoint, "path_params": expected_path},
    )
    assert isinstance(receipt, TransportReceipt)
    assert receipt.operation == operation
    assert receipt.status == "SUCCEEDED"
    assert receipt.network_request_sent is True
    assert receipt.readback_verified is True


def test_list_documents_uses_fixed_endpoint_and_bounded_limit(
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": {"items": [{"id": "doc-123"}]}})

    receipt = OnshapeMcpReadTransport(session, documentless_scope).read(
        "list_documents", {"limit": 7}
    )

    assert session.last_call == ToolCall(
        "onshape_api_call",
        {"endpoint": "getDocuments", "query_params": {"limit": "7"}},
    )
    assert receipt.status == "SUCCEEDED"
    assert receipt.readback_verified is True


@pytest.mark.parametrize(
    ("operation", "response", "expected_evidence"),
    [
        (
            "list_documents",
            {"items": [{"id": "doc-123"}]},
            {"item_count": 1},
        ),
        (
            "list_workspaces",
            {"items": [{"id": "workspace-456"}]},
            {"item_count": 1},
        ),
        (
            "read_elements",
            {"items": [{"id": "element-789"}]},
            {"item_count": 1},
        ),
        (
            "body_details",
            {"bodies": [{"id": "body-1"}]},
            {"body_count": 1},
        ),
        (
            "bounding_boxes",
            {
                "lowX": 0.0,
                "lowY": 0.0,
                "lowZ": 0.0,
                "highX": 1.0,
                "highY": 2.0,
                "highZ": 3.0,
            },
            {"bounds_present": True},
        ),
        (
            "mass_properties",
            {"bodies": {"body-1": {"mass": [1.0]}}},
            {"body_count": 1},
        ),
    ],
)
def test_each_read_accepts_its_minimal_deterministic_invariant(
    operation: str,
    response: object,
    expected_evidence: dict[str, bool | int | float | str],
    scoped_scope: OnshapeScope,
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": response})
    scope = documentless_scope if operation == "list_documents" else scoped_scope

    receipt = OnshapeMcpReadTransport(session, scope).read(operation, {})

    assert receipt.status == "SUCCEEDED"
    assert receipt.readback_verified is True
    assert receipt.evidence_summary == expected_evidence


@pytest.mark.parametrize(
    ("operation", "response"),
    [
        ("list_documents", []),
        ("list_documents", {"items": []}),
        ("list_workspaces", []),
        ("list_workspaces", {"items": []}),
        ("read_elements", []),
        ("read_elements", {"items": []}),
    ],
)
def test_collection_reads_accept_empty_collections(
    operation: str,
    response: object,
    scoped_scope: OnshapeScope,
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": response})
    scope = documentless_scope if operation == "list_documents" else scoped_scope

    receipt = OnshapeMcpReadTransport(session, scope).read(operation, {})

    assert receipt.status == "SUCCEEDED"
    assert receipt.readback_verified is True
    assert receipt.evidence_summary == {"item_count": 0}


@pytest.mark.parametrize(
    ("operation", "response"),
    [
        ("list_documents", {}),
        ("list_workspaces", {}),
        ("read_elements", {}),
        ("body_details", {}),
        ("body_details", {"bodies": []}),
        ("bounding_boxes", {}),
        (
            "bounding_boxes",
            {
                "lowX": 0.0,
                "lowY": 0.0,
                "lowZ": 0.0,
                "highX": 1.0,
                "highY": 2.0,
            },
        ),
        ("mass_properties", {}),
        ("mass_properties", {"bodies": {}}),
    ],
)
def test_each_read_rejects_empty_or_missing_invariant(
    operation: str,
    response: object,
    scoped_scope: OnshapeScope,
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": response})
    scope = documentless_scope if operation == "list_documents" else scoped_scope

    with pytest.raises(LiveTransportError, match="INVALID_RESPONSE"):
        OnshapeMcpReadTransport(session, scope).read(operation, {})


def test_get_document_missing_id_is_invalid_response_not_verified(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": {"name": "private"}})

    with pytest.raises(LiveTransportError, match="INVALID_RESPONSE") as raised:
        OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert "private" not in str(raised.value)


@pytest.mark.parametrize("limit", [1, 100])
def test_list_documents_accepts_inclusive_limit_bounds(
    limit: int, documentless_scope: OnshapeScope
) -> None:
    session = FakeSession({"onshape_api_call": {"items": [{"id": "doc-123"}]}})

    OnshapeMcpReadTransport(session, documentless_scope).read(
        "list_documents", {"limit": limit}
    )

    assert session.last_call.arguments["query_params"] == {"limit": str(limit)}


@pytest.mark.parametrize("limit", [0, 101, True, "10", 1.5])
def test_list_documents_rejects_out_of_range_or_non_integer_limit(
    limit: object, documentless_scope: OnshapeScope
) -> None:
    session = FakeSession()

    with pytest.raises(LivePolicyDenied, match="INVALID_PARAMETERS"):
        OnshapeMcpReadTransport(session, documentless_scope).read(
            "list_documents", {"limit": limit}
        )

    assert session.calls == []


@pytest.mark.parametrize("operation", ["delete_workspace", "raw_http", "create_sketch"])
def test_unknown_or_mutating_operation_is_denied_before_mcp_call(
    operation: str, scoped_scope: OnshapeScope
) -> None:
    session = FakeSession()

    with pytest.raises(LivePolicyDenied, match="OPERATION_DENIED"):
        OnshapeMcpReadTransport(session, scoped_scope).read(operation, {})

    assert session.calls == []


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "endpoint",
        "url",
        "method",
        "body",
        "header_params",
        "file_refs",
        "auth",
        "login",
        "auth_login",
    ],
)
def test_raw_transport_overrides_and_auth_inputs_are_denied(
    unsafe_key: str, scoped_scope: OnshapeScope
) -> None:
    session = FakeSession()

    with pytest.raises(LivePolicyDenied, match="OPERATION_DENIED") as raised:
        OnshapeMcpReadTransport(session, scoped_scope).read(
            "get_document", {unsafe_key: "fake-child-secret"}
        )

    assert session.calls == []
    assert "fake-child-secret" not in str(raised.value)


def test_nested_raw_transport_override_is_denied_without_echoing_body(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession()
    parameters = {"options": {"body": {"secret": "fake-child-secret"}}}

    with pytest.raises(LivePolicyDenied, match="OPERATION_DENIED") as raised:
        OnshapeMcpReadTransport(session, scoped_scope).read("get_document", parameters)

    assert session.calls == []
    assert "fake-child-secret" not in str(raised.value)


def test_documentless_scope_cannot_dispatch_document_reads(
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession()

    with pytest.raises(LivePolicyDenied, match="SCOPE_DENIED"):
        OnshapeMcpReadTransport(session, documentless_scope).read("get_document", {})

    assert session.calls == []


@pytest.mark.parametrize(
    ("operation", "parameters"),
    [
        ("get_document", {"document_id": "other-document"}),
        ("read_elements", {"wvm_id": "other-workspace"}),
        ("body_details", {"element_id": "other-element"}),
    ],
)
def test_caller_identifiers_must_match_approved_scope(
    operation: str,
    parameters: dict[str, object],
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession()

    with pytest.raises(LivePolicyDenied, match="SCOPE_DENIED"):
        OnshapeMcpReadTransport(session, scoped_scope).read(operation, parameters)

    assert session.calls == []


def test_unknown_safe_parameter_is_denied_before_dispatch(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession()

    with pytest.raises(LivePolicyDenied, match="INVALID_PARAMETERS"):
        OnshapeMcpReadTransport(session, scoped_scope).read(
            "get_document", {"unexpected": "value"}
        )

    assert session.calls == []


def test_invalid_wvm_is_denied_at_transport_boundary(
    scoped_scope: OnshapeScope,
) -> None:
    invalid_scope = OnshapeScope.model_construct(
        stack="cad.onshape.com",
        document_id="doc-123",
        wvm="x",
        wvm_id="workspace-456",
        element_id="element-789",
    )
    session = FakeSession()

    with pytest.raises(LivePolicyDenied, match="SCOPE_DENIED"):
        OnshapeMcpReadTransport(session, invalid_scope).read("read_elements", {})

    assert session.calls == []


@pytest.mark.parametrize(
    "operation",
    ["read_elements", "body_details", "bounding_boxes", "mass_properties"],
)
def test_versioned_reads_require_complete_wvm_scope(
    operation: str,
) -> None:
    session = FakeSession()
    scope = OnshapeScope(document_id="doc-123")

    with pytest.raises(LivePolicyDenied, match="SCOPE_DENIED"):
        OnshapeMcpReadTransport(session, scope).read(operation, {})

    assert session.calls == []


@pytest.mark.parametrize(
    "operation",
    ["body_details", "bounding_boxes", "mass_properties"],
)
def test_body_reads_require_element_scope(operation: str) -> None:
    session = FakeSession()
    scope = OnshapeScope(document_id="doc-123", wvm="w", wvm_id="workspace-456")

    with pytest.raises(LivePolicyDenied, match="SCOPE_DENIED"):
        OnshapeMcpReadTransport(session, scope).read(operation, {})

    assert session.calls == []


def test_get_document_requires_matching_id_in_response(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession(
        {"onshape_api_call": {"id": "other-document", "secret": "private"}}
    )

    with pytest.raises(LiveTransportError, match="VERIFICATION_FAILED") as raised:
        OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert "other-document" not in str(raised.value)
    assert "private" not in str(raised.value)


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (401, "AUTH_REQUIRED"),
        (403, "SCOPE_DENIED"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMITED"),
    ],
)
def test_api_status_errors_map_to_stable_codes_without_body_leak(
    status: int,
    expected_code: str,
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession(
        {
            "onshape_api_call": {
                "status_code": status,
                "body": {"secret": "fake-child-secret"},
            }
        }
    )

    with pytest.raises(LiveTransportError, match=expected_code) as raised:
        OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert "fake-child-secret" not in str(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        {"error": "expired"},
        {"error": {"code": "auth_required", "payload": "private"}},
        {"errors": [{"message": "not authenticated", "payload": "private"}]},
        {"error": {"message": "token expired", "payload": "private"}},
        {"error": {"message": "token has expired", "payload": "private"}},
        {"status": "expired", "payload": "private"},
    ],
)
def test_generic_read_auth_aliases_map_to_auth_required_without_body_leak(
    response: object,
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": response})

    with pytest.raises(LiveTransportError, match="AUTH_REQUIRED") as raised:
        OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert "private" not in str(raised.value)


@pytest.mark.parametrize(
    "response", [None, "not-json", {"error": {"secret": "private"}}]
)
def test_invalid_or_error_response_is_sanitized(
    response: object, scoped_scope: OnshapeScope
) -> None:
    session = FakeSession({"onshape_api_call": response})

    with pytest.raises(LiveTransportError) as raised:
        OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert raised.value.code == "INVALID_RESPONSE"
    assert "private" not in str(raised.value)


def test_transport_receipt_contains_no_private_response_body(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession(
        {"onshape_api_call": {"id": "doc-123", "description": "private"}}
    )

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert "private" not in receipt.model_dump_json()
    assert receipt.evidence_summary == {"document_id_matches": True}


def test_mcp_transport_error_code_is_stable_and_sanitized(
    scoped_scope: OnshapeScope,
) -> None:
    class FailingSession(FakeSession):
        def call_tool(self, name: str, arguments: dict[str, object]) -> object:
            self.calls.append(ToolCall(name, arguments))
            raise RuntimeError("fake-child-secret")

    session = FailingSession()

    with pytest.raises(LiveTransportError, match="TRANSPORT_FAILED") as raised:
        OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert "fake-child-secret" not in str(raised.value)


def test_scope_stack_is_fixed_to_cad_onshape_com(
    scoped_scope: OnshapeScope,
) -> None:
    invalid_scope = OnshapeScope.model_construct(
        stack="example.onshape.com",
        document_id="doc-123",
        wvm="w",
        wvm_id="workspace-456",
        element_id="element-789",
    )
    session = FakeSession()

    with pytest.raises(LivePolicyDenied, match="SCOPE_DENIED"):
        OnshapeMcpReadTransport(session, invalid_scope).read("get_document", {})

    assert session.calls == []


def test_action_parameters_are_copied_before_dispatch(
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": {"items": [{"id": "doc-123"}]}})
    parameters: dict[str, Any] = {"limit": 5}

    OnshapeMcpReadTransport(session, documentless_scope).read(
        "list_documents", parameters
    )
    parameters["limit"] = 99

    assert session.last_call.arguments == {
        "endpoint": "getDocuments",
        "query_params": {"limit": "5"},
    }
