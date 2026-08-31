from __future__ import annotations

import pytest
from pydantic import ValidationError

import onshape_agent.contracts as contracts
from onshape_agent.contracts import (
    ApprovalStatus,
    ArtifactRef,
    ArtifactType,
    Capability,
    DesignValue,
    DrawingPlan,
    DrawingView,
    ExecutionMode,
    ExecutionPlan,
    TaskEdge,
    TaskGraph,
    TaskNode,
    ValueStatus,
)


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(
            artifact_id="artifact_1",
            artifact_type=ArtifactType.CAD_SPEC,
            run_id="run_1",
            producer="main_orchestrator",
            content_hash="sha256:abc",
            approval_status=ApprovalStatus.APPROVED,
            surprise="not allowed",
        )


def test_unapproved_assumption_remains_explicit() -> None:
    value = DesignValue(
        value=10,
        unit="mm",
        status=ValueStatus.ASSUMPTION,
        approved=False,
    )

    assert value.status is ValueStatus.ASSUMPTION
    assert value.approved is False


def test_task_graph_rejects_edge_to_missing_node() -> None:
    with pytest.raises(ValidationError, match="missing node"):
        TaskGraph(
            run_id="run_1",
            nodes=[TaskNode(id="cad", capability=Capability.CAD_PLANNING)],
            edges=[TaskEdge(source="cad", target="vision")],
        )


def test_task_graph_rejects_cycles() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        TaskGraph(
            run_id="run_1",
            nodes=[
                TaskNode(id="cad", capability=Capability.CAD_PLANNING),
                TaskNode(id="vision", capability=Capability.VISUAL_QA),
            ],
            edges=[
                TaskEdge(source="cad", target="vision"),
                TaskEdge(source="vision", target="cad"),
            ],
        )


def test_drawing_plan_requires_three_orthographic_views() -> None:
    with pytest.raises(ValidationError, match="front, top, and right"):
        DrawingPlan(
            plan_id="drawing_1",
            approved_design_hash="sha256:approved",
            views=[DrawingView(view_id="front", orientation="front")],
        )


def test_live_scope_allows_missing_document_for_document_discovery() -> None:
    scope_model = getattr(contracts, "OnshapeScope", None)
    assert scope_model is not None

    scope = scope_model(stack="cad.onshape.com")

    assert scope.document_id is None


def test_live_scope_accepts_only_the_approved_stack_and_identifiers() -> None:
    scope_model = getattr(contracts, "OnshapeScope", None)
    assert scope_model is not None

    scope = scope_model(
        document_id="document_123",
        wvm="v",
        wvm_id="version_456",
        element_id="element_789",
    )

    assert scope.stack == "cad.onshape.com"
    assert scope.document_id == "document_123"
    assert scope.wvm == "v"
    assert scope.wvm_id == "version_456"
    assert scope.element_id == "element_789"

    with pytest.raises(ValidationError):
        scope_model(document_id="document_123", stack="enterprise.onshape.com")


def test_transport_receipt_records_real_request_and_readback() -> None:
    receipt_model = getattr(contracts, "TransportReceipt", None)
    assert receipt_model is not None

    receipt = receipt_model(
        operation="get_document",
        status="SUCCEEDED",
        network_request_sent=True,
        readback_verified=True,
        evidence_summary={"document_id_matches": True},
    )

    assert receipt.network_request_sent is True
    assert receipt.readback_verified is True
    assert receipt.evidence_summary == {"document_id_matches": True}


def test_transport_receipt_rejects_private_payloads_and_unknown_fields() -> None:
    receipt_model = getattr(contracts, "TransportReceipt", None)
    assert receipt_model is not None

    with pytest.raises(ValidationError):
        receipt_model(
            operation="get_document",
            status="SUCCEEDED",
            network_request_sent=True,
            readback_verified=True,
            response_body={"name": "private"},
        )


def test_execution_plan_defaults_to_simulated_without_live_scope() -> None:
    plan = ExecutionPlan(
        plan_id="plan_simulated",
        approved_design_hash="sha256:approved",
        target_scope="sandbox",
        actions=[],
    )

    assert plan.execution_mode is ExecutionMode.SIMULATED
    assert plan.onshape_scope is None


def test_execution_plan_accepts_a_scoped_live_read() -> None:
    scope = contracts.OnshapeScope(document_id="document_123")
    plan = ExecutionPlan(
        plan_id="plan_live",
        approved_design_hash="sha256:approved",
        target_scope="sandbox",
        execution_mode=ExecutionMode.LIVE,
        onshape_scope=scope,
        actions=[],
    )

    assert plan.execution_mode is ExecutionMode.LIVE
    assert plan.onshape_scope == scope
