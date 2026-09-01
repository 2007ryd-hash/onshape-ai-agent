from __future__ import annotations

import pytest
from pydantic import ValidationError

from onshape_agent.contracts import (
    CadAction,
    DesignValue,
    ExecutionMode,
    ExecutionPlan,
    OnshapeScope,
    TransportReceipt,
    ValueStatus,
)
from onshape_agent.gateway import CadGateway, RecordingTransport
from onshape_agent.live_transport import LivePolicyDenied, OnshapeMcpReadTransport
from onshape_agent.mcp_stdio import McpTransportError


def make_plan(*actions: CadAction) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan_1",
        approved_design_hash="sha256:approved",
        target_scope="sandbox",
        actions=list(actions),
    )


def make_live_plan(*actions: CadAction) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="live_plan_1",
        approved_design_hash="sha256:approved",
        target_scope="sandbox",
        execution_mode=ExecutionMode.LIVE,
        onshape_scope=OnshapeScope(document_id="document_123"),
        actions=list(actions),
    )


class FakeLiveTransport:
    transport_name = "fake-live"

    def __init__(
        self,
        receipts: list[TransportReceipt] | None = None,
        *,
        preflight_error: Exception | None = None,
        dispatch_error: Exception | None = None,
        sends_network: bool = True,
    ) -> None:
        self.receipts = list(receipts or [])
        self.preflight_error = preflight_error
        self.dispatch_error = dispatch_error
        self.sends_network = sends_network
        self.preflight_actions: list[list[CadAction]] = []
        self.calls: list[CadAction] = []

    def preflight(self, actions: list[CadAction]) -> None:
        self.preflight_actions.append(list(actions))
        if self.preflight_error is not None:
            raise self.preflight_error

    def dispatch(self, action: CadAction) -> TransportReceipt:
        self.calls.append(action)
        if self.dispatch_error is not None:
            raise self.dispatch_error
        if not self.receipts:
            read_kind = action.parameters.get("read_kind")
            return TransportReceipt(
                operation=(
                    read_kind if isinstance(read_kind, str) else action.type
                ),
                status="SUCCEEDED",
                network_request_sent=True,
                readback_verified=True,
            )
        return self.receipts.pop(0)


def read_action(action_id: str = "read_1") -> CadAction:
    return CadAction(
        action_id=action_id,
        type="read_back",
        semantic_id="document",
        parameters={"read_kind": "get_document"},
    )


class FakeMcpSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, tool_name: str, arguments: dict[str, object]) -> object:
        self.calls.append((tool_name, dict(arguments)))
        if not self.responses:
            raise AssertionError("unexpected MCP call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_delete_workspace_is_denied_before_transport_dispatch() -> None:
    transport = RecordingTransport()
    gateway = CadGateway(transport)
    plan = make_plan(
        CadAction(
            action_id="delete_1",
            type="delete_workspace",
            semantic_id="workspace",
        )
    )

    report = gateway.execute(plan)

    assert report.status == "DENIED"
    assert report.code == "OPERATION_NOT_ALLOWED"
    assert report.network_request_sent is False
    assert transport.calls == []


def test_unknown_operation_is_denied() -> None:
    report = CadGateway(RecordingTransport()).execute(
        make_plan(
            CadAction(
                action_id="mystery_1",
                type="invent_feature",
                semantic_id="mystery",
            )
        )
    )

    assert report.status == "DENIED"
    assert report.network_request_sent is False


def test_unapproved_assumption_blocks_all_actions() -> None:
    transport = RecordingTransport()
    plan = make_plan(
        CadAction(
            action_id="sketch_1",
            type="ensure_sketch",
            semantic_id="base_sketch",
        )
    )
    plan.assumptions.append(
        DesignValue(
            value=10,
            unit="mm",
            status=ValueStatus.ASSUMPTION,
            approved=False,
        )
    )

    report = CadGateway(transport).execute(plan)

    assert report.code == "UNAPPROVED_ASSUMPTION"
    assert transport.calls == []


def test_allowlisted_actions_reach_recording_transport_in_dependency_order() -> None:
    transport = RecordingTransport()
    plan = make_plan(
        CadAction(
            action_id="extrude_1",
            type="ensure_extrude",
            semantic_id="base_plate",
            depends_on=["sketch_1"],
        ),
        CadAction(
            action_id="sketch_1",
            type="ensure_sketch",
            semantic_id="base_sketch",
        ),
    )

    report = CadGateway(transport).execute(plan)

    assert report.status == "EXECUTED"
    assert [call.action_id for call in transport.calls] == ["sketch_1", "extrude_1"]
    assert report.network_request_sent is False


def test_recording_transport_returns_a_typed_simulated_receipt() -> None:
    transport = RecordingTransport()

    receipt = transport.dispatch(
        CadAction(
            action_id="sketch_1",
            type="ensure_sketch",
            semantic_id="base_sketch",
        )
    )

    assert isinstance(receipt, TransportReceipt)
    assert receipt.operation == "ensure_sketch"
    assert receipt.status == "SUCCEEDED"
    assert receipt.network_request_sent is False


def test_live_gateway_preflights_entire_plan_before_first_request() -> None:
    transport = FakeLiveTransport()
    report = CadGateway(transport).execute(
        make_live_plan(
            read_action("read_1"),
            CadAction(
                action_id="delete_1",
                type="delete_workspace",
                semantic_id="workspace",
            ),
        )
    )

    assert report.status == "DENIED"
    assert transport.calls == []


def test_live_gateway_rejects_invalid_scope_before_transport_preflight() -> None:
    transport = FakeLiveTransport()
    invalid_scope = OnshapeScope.model_construct(
        stack="enterprise.onshape.com",
        document_id="document_123",
    )
    plan = ExecutionPlan(
        plan_id="live_plan_1",
        approved_design_hash="sha256:approved",
        target_scope="onshape",
        execution_mode=ExecutionMode.LIVE,
        onshape_scope=invalid_scope,
        actions=[read_action()],
    )

    report = CadGateway(transport).execute(plan)

    assert report.status == "DENIED"
    assert report.code == "SCOPE_DENIED"
    assert transport.preflight_actions == []
    assert transport.calls == []


def test_live_gateway_passes_the_whole_plan_to_transport_preflight() -> None:
    transport = FakeLiveTransport()
    plan = make_live_plan(read_action("read_1"), read_action("read_2"))

    report = CadGateway(transport).execute(plan)

    assert report.status == "EXECUTED"
    assert transport.preflight_actions == [plan.actions]
    assert [action.action_id for action in transport.calls] == ["read_1", "read_2"]


def test_gateway_denies_when_transport_mutates_preflight_snapshot() -> None:
    class SnapshotMutatingTransport(FakeLiveTransport):
        def preflight(self, actions: list[CadAction]) -> None:
            super().preflight(actions)
            actions[0].parameters["read_kind"] = "list_documents"

    transport = SnapshotMutatingTransport()

    report = CadGateway(transport).execute(make_live_plan(read_action()))

    assert report.status == "DENIED"
    assert report.code == "PLAN_MUTATED"
    assert report.network_request_sent is False
    assert transport.calls == []


def test_gateway_dispatches_snapshot_when_original_plan_mutates_in_preflight() -> None:
    plan = make_live_plan(read_action())

    class ExternalPlanMutatingTransport(FakeLiveTransport):
        def preflight(self, actions: list[CadAction]) -> None:
            super().preflight(actions)
            plan.actions[0].parameters["read_kind"] = "list_documents"

    transport = ExternalPlanMutatingTransport()

    report = CadGateway(transport).execute(plan)

    assert report.status == "EXECUTED"
    assert transport.calls[0].parameters["read_kind"] == "get_document"
    assert plan.actions[0].parameters["read_kind"] == "list_documents"


def test_live_gateway_executes_real_read_transport_with_verified_readback() -> None:
    session = FakeMcpSession([{"id": "document_123", "name": "private"}])
    transport = OnshapeMcpReadTransport(
        session,
        OnshapeScope(document_id="document_123"),
    )

    report = CadGateway(transport).execute(make_live_plan(read_action()))

    assert report.status == "EXECUTED"
    assert report.execution_mode is ExecutionMode.LIVE
    assert report.transport_name == "onshape-mcp-stdio"
    assert report.network_request_sent is True
    assert report.readback_verified is True
    assert len(report.receipts) == 1
    assert session.calls == [
        (
            "onshape_api_call",
            {
                "endpoint": "getDocument",
                "path_params": {"did": "document_123"},
            },
        )
    ]


def test_real_read_transport_preflights_later_invalid_read_without_mcp_call() -> None:
    session = FakeMcpSession([{"id": "document_123"}])
    transport = OnshapeMcpReadTransport(
        session,
        OnshapeScope(document_id="document_123"),
    )
    invalid_later_read = CadAction(
        action_id="delete_1",
        type="read_back",
        semantic_id="workspace",
        depends_on=["read_1"],
        parameters={"read_kind": "delete_workspace"},
    )

    report = CadGateway(transport).execute(
        make_live_plan(read_action("read_1"), invalid_later_read)
    )

    assert report.status == "DENIED"
    assert report.code == "OPERATION_DENIED"
    assert session.calls == []


def test_real_read_transport_dispatch_rejects_mutating_action() -> None:
    session = FakeMcpSession([])
    transport = OnshapeMcpReadTransport(
        session,
        OnshapeScope(document_id="document_123"),
    )

    with pytest.raises(LivePolicyDenied, match="OPERATION_DENIED"):
        transport.dispatch(
            CadAction(
                action_id="sketch_1",
                type="ensure_sketch",
                semantic_id="base_sketch",
            )
        )

    assert session.calls == []


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (McpTransportError("TRANSPORT_TIMEOUT"), "TRANSPORT_TIMEOUT"),
        (RuntimeError("private-child-secret"), "TRANSPORT_FAILED"),
    ],
)
def test_read_returns_failed_receipt_after_mcp_call_error(
    error: Exception, expected_code: str
) -> None:
    session = FakeMcpSession([error])
    transport = OnshapeMcpReadTransport(
        session,
        OnshapeScope(document_id="document_123"),
    )

    receipt = transport.read("get_document", {})

    assert receipt.status == "FAILED"
    assert receipt.network_request_sent is True
    assert receipt.readback_verified is False
    assert receipt.error_code == expected_code
    assert "private-child-secret" not in receipt.model_dump_json()
    assert len(session.calls) == 1


def test_gateway_preserves_network_sent_when_live_receipt_reports_call_failure(
) -> None:
    session = FakeMcpSession([McpTransportError("TRANSPORT_TIMEOUT")])
    transport = OnshapeMcpReadTransport(
        session,
        OnshapeScope(document_id="document_123"),
    )

    report = CadGateway(transport).execute(make_live_plan(read_action()))

    assert report.status == "FAILED"
    assert report.code == "TRANSPORT_TIMEOUT"
    assert report.network_request_sent is True
    assert report.readback_verified is False
    assert len(report.receipts) == 1
    assert report.receipts[0].status == "FAILED"


def test_live_gateway_derives_network_status_from_receipts() -> None:
    transport = FakeLiveTransport(
        receipts=[
            TransportReceipt(
                operation="get_document",
                status="SUCCEEDED",
                network_request_sent=True,
                readback_verified=True,
            )
        ],
        sends_network=False,
    )

    report = CadGateway(transport).execute(make_live_plan(read_action()))

    assert report.status == "EXECUTED"
    assert report.network_request_sent is True


def test_live_gateway_requires_verified_readback() -> None:
    transport = FakeLiveTransport(
        receipts=[
            TransportReceipt(
                operation="get_document",
                status="SUCCEEDED",
                network_request_sent=True,
                readback_verified=False,
            )
        ]
    )

    report = CadGateway(transport).execute(make_live_plan(read_action()))

    assert report.status == "FAILED"
    assert report.code == "VERIFICATION_FAILED"


def test_live_gateway_requires_every_receipt_to_be_successful_and_verified() -> None:
    transport = FakeLiveTransport(
        receipts=[
            TransportReceipt(
                operation="get_document",
                status="SUCCEEDED",
                network_request_sent=True,
                readback_verified=True,
            ),
            TransportReceipt(
                operation="get_document",
                status="FAILED",
                network_request_sent=True,
                readback_verified=False,
                error_code="INVALID_RESPONSE",
            ),
        ]
    )

    report = CadGateway(transport).execute(
        make_live_plan(read_action("read_1"), read_action("read_2"))
    )

    assert report.status == "FAILED"
    assert report.code == "INVALID_RESPONSE"
    assert report.network_request_sent is True


def test_transport_exception_maps_to_sanitized_failed_report() -> None:
    transport = FakeLiveTransport(
        dispatch_error=RuntimeError("Authorization Bearer super-secret-token")
    )

    report = CadGateway(transport).execute(make_live_plan(read_action()))

    assert report.status == "FAILED"
    assert report.code == "TRANSPORT_FAILED"
    assert "super-secret-token" not in report.model_dump_json()


def test_transport_preflight_exception_prevents_dispatch() -> None:
    transport = FakeLiveTransport(
        preflight_error=RuntimeError("private server response")
    )

    report = CadGateway(transport).execute(make_live_plan(read_action()))

    assert report.status == "FAILED"
    assert report.code == "TRANSPORT_FAILED"
    assert transport.calls == []


def test_live_policy_preflight_error_is_denied_without_dispatch() -> None:
    transport = FakeLiveTransport(
        preflight_error=LivePolicyDenied("SCOPE_DENIED", "private scope details")
    )

    report = CadGateway(transport).execute(make_live_plan(read_action()))

    assert report.status == "DENIED"
    assert report.code == "SCOPE_DENIED"
    assert transport.calls == []


def test_gateway_rejects_untyped_transport_receipts_without_an_adapter() -> None:
    class LegacyTransport:
        transport_name = "legacy"

        def preflight(self, plan: ExecutionPlan) -> None:
            return None

        def dispatch(self, action: CadAction) -> dict[str, object]:
            return {"status": "RECORDED", "action_id": action.action_id}

    report = CadGateway(LegacyTransport()).execute(
        make_plan(
            CadAction(
                action_id="sketch_1",
                type="ensure_sketch",
                semantic_id="base_sketch",
            )
        )
    )

    assert report.status == "FAILED"
    assert report.code == "TRANSPORT_FAILED"
    assert report.receipts == []


def test_execution_plan_requires_approval_hash() -> None:
    with pytest.raises(ValidationError):
        ExecutionPlan(
            plan_id="plan_1",
            approved_design_hash="",
            target_scope="sandbox",
            actions=[],
        )
