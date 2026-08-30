"""Deterministic task selection and bounded repair routing for the main agent."""

from __future__ import annotations

from .contracts import (
    Capability,
    Diagnosis,
    IssueType,
    RunState,
    TaskEdge,
    TaskGraph,
    TaskKind,
    TaskNode,
)

GRAPH_CAPABILITIES: dict[TaskKind, tuple[Capability, ...]] = {
    TaskKind.FULL_DESIGN: (
        Capability.ENGINEERING_ANALYSIS,
        Capability.PHYSICS_SOLVER,
        Capability.CAD_PLANNING,
        Capability.GEOMETRY_VERIFICATION,
        Capability.DRAWING_PLANNING,
        Capability.VISUAL_QA,
    ),
    TaskKind.CAD_EDIT: (
        Capability.CAD_PLANNING,
        Capability.GEOMETRY_VERIFICATION,
        Capability.VISUAL_QA,
    ),
    TaskKind.DRAWING_ONLY: (
        Capability.DRAWING_PLANNING,
        Capability.VISUAL_QA,
    ),
    TaskKind.ANALYSIS_ONLY: (
        Capability.ENGINEERING_ANALYSIS,
        Capability.PHYSICS_SOLVER,
    ),
}


REPAIR_ROUTES: dict[IssueType, tuple[str, RunState]] = {
    IssueType.ENGINEERING_MODEL_ERROR: (
        "engineering_agent",
        RunState.ANALYSIS_PLANNING,
    ),
    IssueType.CAD_GEOMETRY_ERROR: ("cad_agent", RunState.CAD_PLANNING),
    IssueType.ASSEMBLY_MATE_ERROR: ("cad_agent", RunState.CAD_PLANNING),
    IssueType.DRAWING_ERROR: ("drawing_agent", RunState.DRAWING_PLANNING),
    IssueType.GATEWAY_API_ERROR: ("cad_gateway", RunState.CAD_EXECUTION),
    IssueType.VISUAL_UNCERTAINTY: ("visual_qa_agent", RunState.VISUAL_QA),
    IssueType.UNRESOLVED_REQUIREMENT: ("user", RunState.USER_CONFIRMATION),
}


class MainOrchestrator:
    """Own graph construction and repair transitions; workers own no state."""

    def select_graph(self, task_kind: TaskKind, run_id: str) -> TaskGraph:
        capabilities = GRAPH_CAPABILITIES[task_kind]
        nodes = [
            TaskNode(
                id=f"step_{index}_{capability.value}",
                capability=capability,
                model_profile=(
                    "worker_luna_max"
                    if capability
                    in {
                        Capability.ENGINEERING_ANALYSIS,
                        Capability.CAD_PLANNING,
                        Capability.DRAWING_PLANNING,
                        Capability.VISUAL_QA,
                    }
                    else None
                ),
                executor=(
                    "deterministic"
                    if capability
                    in {
                        Capability.PHYSICS_SOLVER,
                        Capability.GEOMETRY_VERIFICATION,
                    }
                    else None
                ),
            )
            for index, capability in enumerate(capabilities, start=1)
        ]
        edges = [
            TaskEdge(source=source.id, target=target.id)
            for source, target in zip(nodes, nodes[1:])
        ]
        return TaskGraph(run_id=run_id, nodes=nodes, edges=edges)

    def diagnose(
        self,
        issue_type: IssueType,
        *,
        attempt: int,
        max_attempts: int,
    ) -> Diagnosis:
        if attempt >= max_attempts:
            return Diagnosis(
                issue_type=issue_type,
                repair_target=None,
                next_state=RunState.BLOCKED,
                attempt=attempt,
                max_attempts=max_attempts,
            )
        repair_target, next_state = REPAIR_ROUTES[issue_type]
        return Diagnosis(
            issue_type=issue_type,
            repair_target=repair_target,
            next_state=next_state,
            attempt=attempt,
            max_attempts=max_attempts,
        )
