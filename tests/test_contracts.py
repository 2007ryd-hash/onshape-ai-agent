from __future__ import annotations

import pytest
from pydantic import ValidationError

from onshape_agent.contracts import (
    ApprovalStatus,
    ArtifactRef,
    ArtifactType,
    Capability,
    DesignValue,
    DrawingPlan,
    DrawingView,
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
