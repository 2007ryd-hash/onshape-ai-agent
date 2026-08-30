from __future__ import annotations

from onshape_agent.contracts import Capability, IssueType, RunState, TaskKind
from onshape_agent.orchestrator import MainOrchestrator


def capabilities_for(task_kind: TaskKind) -> list[Capability]:
    graph = MainOrchestrator().select_graph(task_kind, run_id="run_1")
    return [node.capability for node in graph.nodes]


def test_full_design_uses_all_v1_agent_capabilities() -> None:
    assert capabilities_for(TaskKind.FULL_DESIGN) == [
        Capability.ENGINEERING_ANALYSIS,
        Capability.PHYSICS_SOLVER,
        Capability.CAD_PLANNING,
        Capability.GEOMETRY_VERIFICATION,
        Capability.DRAWING_PLANNING,
        Capability.VISUAL_QA,
    ]


def test_cad_edit_skips_engineering_and_drawing() -> None:
    assert capabilities_for(TaskKind.CAD_EDIT) == [
        Capability.CAD_PLANNING,
        Capability.GEOMETRY_VERIFICATION,
        Capability.VISUAL_QA,
    ]


def test_drawing_only_uses_drawing_and_visual_qa() -> None:
    assert capabilities_for(TaskKind.DRAWING_ONLY) == [
        Capability.DRAWING_PLANNING,
        Capability.VISUAL_QA,
    ]


def test_analysis_only_skips_cad() -> None:
    assert capabilities_for(TaskKind.ANALYSIS_ONLY) == [
        Capability.ENGINEERING_ANALYSIS,
        Capability.PHYSICS_SOLVER,
    ]


def test_mate_issue_routes_back_to_cad_agent() -> None:
    diagnosis = MainOrchestrator().diagnose(
        IssueType.ASSEMBLY_MATE_ERROR,
        attempt=1,
        max_attempts=3,
    )

    assert diagnosis.repair_target == "cad_agent"
    assert diagnosis.next_state is RunState.CAD_PLANNING


def test_drawing_issue_routes_to_drawing_agent() -> None:
    diagnosis = MainOrchestrator().diagnose(
        IssueType.DRAWING_ERROR,
        attempt=1,
        max_attempts=3,
    )

    assert diagnosis.repair_target == "drawing_agent"
    assert diagnosis.next_state is RunState.DRAWING_PLANNING


def test_exhausted_repair_budget_blocks_run() -> None:
    diagnosis = MainOrchestrator().diagnose(
        IssueType.CAD_GEOMETRY_ERROR,
        attempt=3,
        max_attempts=3,
    )

    assert diagnosis.repair_target is None
    assert diagnosis.next_state is RunState.BLOCKED
