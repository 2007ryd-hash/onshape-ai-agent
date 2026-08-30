from __future__ import annotations

import pytest
from pydantic import ValidationError

from onshape_agent.contracts import CadAction, DesignValue, ExecutionPlan, ValueStatus
from onshape_agent.gateway import CadGateway, RecordingTransport


def make_plan(*actions: CadAction) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan_1",
        approved_design_hash="sha256:approved",
        target_scope="sandbox",
        actions=list(actions),
    )


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


def test_execution_plan_requires_approval_hash() -> None:
    with pytest.raises(ValidationError):
        ExecutionPlan(
            plan_id="plan_1",
            approved_design_hash="",
            target_scope="sandbox",
            actions=[],
        )
