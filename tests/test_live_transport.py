from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import onshape_agent.live_transport as live_transport
from onshape_agent.contracts import OnshapeScope, TransportReceipt
from onshape_agent.live_transport import (
    LivePolicyDenied,
    OnshapeMcpReadTransport,
)
from onshape_agent.mcp_stdio import McpTransportError


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
        if isinstance(response, Exception):
            raise response
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


def assert_failed_receipt(
    receipt: TransportReceipt, code: str, *, network_request_sent: bool = True
) -> None:
    assert receipt.status == "FAILED"
    assert receipt.error_code == code
    assert receipt.network_request_sent is network_request_sent
    assert receipt.readback_verified is False


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


def test_mass_properties_repeated_integer_coordinates_are_valid(
    scoped_scope: OnshapeScope,
) -> None:
    import json

    response = json.loads('{"bodies":{"b1":{"mass":[1,1,1],"centroid":[0,0,0]}}}')
    session = FakeSession({"onshape_api_call": response})
    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("mass_properties")
    assert receipt.status == "SUCCEEDED"
    assert receipt.readback_verified is True
    assert receipt.evidence_summary == {"body_count": 1}


def test_error_marker_detects_actual_container_cycle() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    assert live_transport._contains_error_marker(cyclic) is True


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

    receipt = OnshapeMcpReadTransport(session, OnshapeScope()).auth_status()

    assert_failed_receipt(receipt, "AUTH_REQUIRED")
    assert "secret" not in receipt.model_dump_json()


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

    receipt = OnshapeMcpReadTransport(session, OnshapeScope()).auth_status()

    assert_failed_receipt(receipt, "INVALID_RESPONSE")


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
        "body_details": {"bodies": [{"id": "body-1", "type": "solid"}]},
        "bounding_boxes": {
            "lowX": 0.0,
            "lowY": 0.0,
            "lowZ": 0.0,
            "highX": 1.0,
            "highY": 1.0,
            "highZ": 1.0,
        },
        "mass_properties": {"bodies": {"body-1": {"mass": [1.0]}}},
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


def test_endpoint_allowlist_is_private_immutable_and_route_cannot_be_mutated(
    scoped_scope: OnshapeScope,
) -> None:
    with pytest.raises(TypeError):
        live_transport._EXPECTED_ENDPOINTS["get_document"] = "deleteDocument"

    session = FakeSession({"onshape_api_call": {"id": "doc-123"}})
    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert receipt.status == "SUCCEEDED"
    assert session.last_call.arguments["endpoint"] == "getDocument"


def test_transport_uses_a_private_scope_snapshot(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": {"id": "doc-123"}})
    transport = OnshapeMcpReadTransport(session, scoped_scope)

    scoped_scope.document_id = "other-document"
    scoped_scope.wvm_id = "other-workspace"
    scoped_scope.element_id = "other-element"

    receipt = transport.read("get_document", {})

    assert receipt.status == "SUCCEEDED"
    assert session.last_call.arguments["path_params"] == {"did": "doc-123"}


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
            {"bodies": [{"id": "body-1", "type": "solid"}]},
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
        (
            "list_documents",
            [{"id": "doc-123", "status": "active", "message": "description"}],
        ),
        (
            "list_workspaces",
            {
                "items": [
                    {
                        "id": "workspace-456",
                        "status": "active",
                        "message": "description",
                    }
                ]
            },
        ),
        (
            "read_elements",
            [{"id": "element-789", "status": "active", "message": "description"}],
        ),
    ],
)
def test_collection_reads_allow_business_status_and_description_message(
    operation: str,
    response: object,
    scoped_scope: OnshapeScope,
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": response})
    scope = documentless_scope if operation == "list_documents" else scoped_scope

    receipt = OnshapeMcpReadTransport(session, scope).read(operation, {})

    assert receipt.status == "SUCCEEDED"
    assert receipt.evidence_summary == {"item_count": 1}


@pytest.mark.parametrize(
    "operation", ["list_documents", "list_workspaces", "read_elements"]
)
def test_collection_reads_reject_recursive_error_markers_in_top_level_lists(
    operation: str,
    scoped_scope: OnshapeScope,
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession(
        {
            "onshape_api_call": [
                {"error": {"message": "private-error"}},
                {"nested": [{"status": "error"}]},
                {"nested": [{"message": "private-message"}]},
            ]
        }
    )
    scope = documentless_scope if operation == "list_documents" else scoped_scope

    receipt = OnshapeMcpReadTransport(session, scope).read(operation, {})

    assert_failed_receipt(receipt, "INVALID_RESPONSE")
    assert "private-error" not in receipt.model_dump_json()
    assert "private-message" not in receipt.model_dump_json()


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

    receipt = OnshapeMcpReadTransport(session, scope).read(operation, {})

    assert_failed_receipt(receipt, "INVALID_RESPONSE")


@pytest.mark.parametrize(
    "response",
    [
        {"bodies": [{"type": "solid"}]},
        {"bodies": [{"id": "body-1"}]},
        {"bodies": [{"id": "body-1", "type": ""}]},
        {"bodies": [None]},
    ],
)
def test_body_details_requires_non_empty_body_id_and_type(
    response: object,
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": response})

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("body_details", {})

    assert_failed_receipt(receipt, "INVALID_RESPONSE")


@pytest.mark.parametrize(
    "response",
    [
        {"bodies": {"body-1": None}},
        {"bodies": {"body-1": {}}},
        {"bodies": {"body-1": {"mass": "not-numeric"}}},
        {"bodies": {"body-1": {"mass": [None]}}},
    ],
)
def test_mass_properties_requires_non_null_numeric_body_values(
    response: object,
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": response})

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("mass_properties", {})

    assert_failed_receipt(receipt, "INVALID_RESPONSE")


@pytest.mark.parametrize(
    "response",
    [
        {
            "lowX": 2.0,
            "lowY": 0.0,
            "lowZ": 0.0,
            "highX": 1.0,
            "highY": 1.0,
            "highZ": 1.0,
        },
        {
            "lowX": 0.0,
            "lowY": None,
            "lowZ": 0.0,
            "highX": 1.0,
            "highY": 1.0,
            "highZ": 1.0,
        },
        {
            "lowX": 0.0,
            "lowY": 0.0,
            "lowZ": 0.0,
            "highX": float("inf"),
            "highY": 1.0,
            "highZ": 1.0,
        },
    ],
)
def test_bounding_boxes_require_finite_non_reversed_axes(
    response: object,
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": response})

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("bounding_boxes", {})

    assert_failed_receipt(receipt, "INVALID_RESPONSE")


@pytest.mark.parametrize("status", ["active", "ok", "succeeded"])
def test_root_business_status_allows_valid_collection_response(
    status: str,
    documentless_scope: OnshapeScope,
) -> None:
    session = FakeSession(
        {
            "onshape_api_call": {
                "status": status,
                "items": [{"id": "doc-123"}],
            }
        }
    )

    receipt = OnshapeMcpReadTransport(session, documentless_scope).read(
        "list_documents", {}
    )

    assert receipt.status == "SUCCEEDED"
    assert receipt.evidence_summary == {"item_count": 1}


@pytest.mark.parametrize(
    "status", ["error", "failed", "failure", "unauthorized", "expired"]
)
def test_root_error_status_rejects_success_shaped_responses(
    status: str,
    scoped_scope: OnshapeScope,
    documentless_scope: OnshapeScope,
) -> None:
    collection_session = FakeSession(
        {
            "onshape_api_call": {
                "status": status,
                "items": [{"id": "doc-123"}],
            }
        }
    )
    collection_receipt = OnshapeMcpReadTransport(
        collection_session, documentless_scope
    ).read("list_documents", {})
    assert collection_receipt.status == "FAILED"

    document_session = FakeSession(
        {"onshape_api_call": {"status": status, "id": "doc-123"}}
    )
    document_receipt = OnshapeMcpReadTransport(document_session, scoped_scope).read(
        "get_document", {}
    )
    assert document_receipt.status == "FAILED"

    auth_session = FakeSession(
        {"onshape_auth_status": {"status": status, "authenticated": True}}
    )
    auth_receipt = OnshapeMcpReadTransport(auth_session, OnshapeScope()).auth_status()
    assert auth_receipt.status == "FAILED"


def test_get_document_missing_id_is_invalid_response_not_verified(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession({"onshape_api_call": {"name": "private"}})

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert_failed_receipt(receipt, "INVALID_RESPONSE")
    assert "private" not in receipt.model_dump_json()


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

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert_failed_receipt(receipt, "VERIFICATION_FAILED")
    assert "other-document" not in receipt.model_dump_json()
    assert "private" not in receipt.model_dump_json()


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

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert_failed_receipt(receipt, expected_code)
    assert "fake-child-secret" not in receipt.model_dump_json()


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

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert_failed_receipt(receipt, "AUTH_REQUIRED")
    assert "private" not in receipt.model_dump_json()


@pytest.mark.parametrize(
    "response", [None, "not-json", {"error": {"secret": "private"}}]
)
def test_invalid_or_error_response_is_sanitized(
    response: object, scoped_scope: OnshapeScope
) -> None:
    session = FakeSession({"onshape_api_call": response})

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert_failed_receipt(receipt, "INVALID_RESPONSE")
    assert "private" not in receipt.model_dump_json()


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

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert_failed_receipt(receipt, "TRANSPORT_FAILED", network_request_sent=False)
    assert "fake-child-secret" not in receipt.model_dump_json()


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


def test_live_receipt_uses_mcp_error_network_request_state(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession(
        {
            "onshape_api_call": McpTransportError(
                "TRANSPORT_TIMEOUT", network_request_sent=False
            )
        }
    )

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert_failed_receipt(receipt, "TRANSPORT_TIMEOUT", network_request_sent=False)
    assert receipt.network_request_sent is False


def test_live_receipt_marks_mcp_error_after_write_as_network_sent(
    scoped_scope: OnshapeScope,
) -> None:
    session = FakeSession(
        {
            "onshape_api_call": McpTransportError(
                "TRANSPORT_TIMEOUT", network_request_sent=True
            )
        }
    )

    receipt = OnshapeMcpReadTransport(session, scoped_scope).read("get_document", {})

    assert_failed_receipt(receipt, "TRANSPORT_TIMEOUT")
