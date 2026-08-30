"""Network-free V1 demonstration of the supervised artifact pipeline."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .contracts import (
    ApprovalStatus,
    ArtifactType,
    CadAction,
    ExecutionPlan,
    IssueType,
    RunState,
    TaskKind,
    VisualIssue,
    VisualReport,
)
from .gateway import CadGateway, RecordingTransport
from .orchestrator import MainOrchestrator
from .runlog import RunLog


def run_demo(output: Path) -> dict[str, object]:
    """Run a safe simulation that records a visual issue and repair route."""

    run_id = f"run_{uuid4().hex[:12]}"
    log = RunLog(output, run_id=run_id)
    log.create_manifest(main_model="gpt-5.6-sol", reasoning_effort="max")
    log.append_event(
        actor="main_orchestrator",
        stage=RunState.INTAKE,
        event="RUN_STARTED",
    )

    orchestrator = MainOrchestrator()
    graph = orchestrator.select_graph(TaskKind.FULL_DESIGN, run_id=run_id)
    log.write_artifact(
        artifact_id="task_graph_v1",
        artifact_type=ArtifactType.TASK_GRAPH,
        producer="main_orchestrator",
        payload=graph.model_dump(mode="json"),
        approval_status=ApprovalStatus.APPROVED,
    )
    log.append_event(
        actor="main_orchestrator",
        stage=RunState.INTAKE,
        event="TASK_GRAPH_SELECTED",
        details={"task_kind": TaskKind.FULL_DESIGN.value},
    )

    plan = ExecutionPlan(
        plan_id="base_plate_plan_v1",
        approved_design_hash="sha256:demo-approved-design",
        target_scope="sandbox",
        actions=[
            CadAction(
                action_id="sketch_1",
                type="ensure_sketch",
                semantic_id="base_plate_sketch",
                parameters={"plane": "TOP"},
            ),
            CadAction(
                action_id="extrude_1",
                type="ensure_extrude",
                semantic_id="base_plate",
                depends_on=["sketch_1"],
                parameters={"source_sketch": "base_plate_sketch", "depth_mm": 8},
            ),
        ],
    )
    log.write_artifact(
        artifact_id="execution_plan_v1",
        artifact_type=ArtifactType.EXECUTION_PLAN,
        producer="cad_agent",
        payload=plan.model_dump(mode="json"),
        approval_status=ApprovalStatus.APPROVED,
    )
    transport = RecordingTransport()
    gateway_report = CadGateway(transport).execute(plan)
    log.write_artifact(
        artifact_id="execution_report_v1",
        artifact_type=ArtifactType.EXECUTION_REPORT,
        producer="cad_gateway",
        payload=gateway_report.model_dump(mode="json"),
    )
    log.append_event(
        actor="cad_gateway",
        stage=RunState.CAD_EXECUTION,
        event="CAD_PLAN_EXECUTED",
        details=gateway_report.model_dump(mode="json"),
    )

    visual_report = VisualReport(
        report_id="visual_report_v1",
        mode="simulated",
        cad_spec_artifact_id="execution_plan_v1",
        cad_render_artifacts=["simulated_cad_front_render"],
        drawing_render_artifacts=["simulated_drawing_front_view"],
        issues=[
            VisualIssue(
                issue_id="visual_issue_1",
                issue_type=IssueType.ASSEMBLY_MATE_ERROR,
                severity="warning",
                confidence=0.91,
                observed_in=[
                    "simulated_cad_front_render",
                    "simulated_drawing_front_view",
                ],
                related_semantic_ids=["base_plate"],
            )
        ],
    )
    log.write_artifact(
        artifact_id="visual_report_v1",
        artifact_type=ArtifactType.VISUAL_REPORT,
        producer="visual_qa_agent",
        payload=visual_report.model_dump(mode="json"),
    )
    log.append_event(
        actor="visual_qa_agent",
        stage=RunState.VISUAL_QA,
        event="VISUAL_ISSUE_REPORTED",
        details={"mode": "simulated", "issue_count": 1},
    )

    diagnosis = orchestrator.diagnose(
        IssueType.ASSEMBLY_MATE_ERROR,
        attempt=1,
        max_attempts=3,
    )
    log.write_artifact(
        artifact_id="diagnosis_v1",
        artifact_type=ArtifactType.DIAGNOSIS,
        producer="main_orchestrator",
        payload=diagnosis.model_dump(mode="json"),
    )
    log.append_event(
        actor="main_orchestrator",
        stage=diagnosis.next_state,
        event="REPAIR_ROUTED",
        details=diagnosis.model_dump(mode="json"),
    )
    return {
        "status": "REPAIR_ROUTED",
        "run_id": run_id,
        "run_dir": str(log.run_dir.resolve()),
        "network_request_sent": gateway_report.network_request_sent,
        "repair_target": diagnosis.repair_target,
        "visual_mode": visual_report.mode,
    }
