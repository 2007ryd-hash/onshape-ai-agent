"""Strict, versioned contracts exchanged through the artifact store."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared fields and coercion surprises."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ArtifactType(StrEnum):
    TASK_GRAPH = "task_graph"
    PROBLEM_BRIEF = "problem_brief"
    ENGINEERING_MODEL = "engineering_model"
    ANALYSIS_RESULT = "analysis_result"
    APPROVED_DESIGN = "approved_design"
    CAD_SPEC = "cad_spec"
    EXECUTION_PLAN = "execution_plan"
    EXECUTION_REPORT = "execution_report"
    DRAWING_PLAN = "drawing_plan"
    VISUAL_REPORT = "visual_report"
    DIAGNOSIS = "diagnosis"


class Capability(StrEnum):
    ENGINEERING_ANALYSIS = "engineering_analysis"
    PHYSICS_SOLVER = "physics_solver"
    CAD_PLANNING = "cad_planning"
    GEOMETRY_VERIFICATION = "geometry_verification"
    DRAWING_PLANNING = "drawing_planning"
    VISUAL_QA = "visual_qa"


class TaskKind(StrEnum):
    FULL_DESIGN = "full_design"
    CAD_EDIT = "cad_edit"
    DRAWING_ONLY = "drawing_only"
    ANALYSIS_ONLY = "analysis_only"


class ExecutionMode(StrEnum):
    SIMULATED = "simulated"
    LIVE = "live"


class OnshapeScope(StrictModel):
    """Approved, bounded identifiers for live Onshape reads."""

    stack: Literal["cad.onshape.com"] = "cad.onshape.com"
    document_id: str | None = Field(default=None, min_length=1)
    wvm: Literal["w", "v", "m"] | None = None
    wvm_id: str | None = Field(default=None, min_length=1)
    element_id: str | None = Field(default=None, min_length=1)


class TransportReceipt(StrictModel):
    """Safe summary of one deterministic transport operation."""

    operation: str = Field(min_length=1)
    status: Literal["SUCCEEDED", "FAILED"]
    network_request_sent: bool
    readback_verified: bool
    evidence_summary: dict[str, bool | int | float | str] = Field(
        default_factory=dict
    )
    error_code: str | None = Field(default=None, min_length=1)


class IssueType(StrEnum):
    ENGINEERING_MODEL_ERROR = "engineering_model_error"
    CAD_GEOMETRY_ERROR = "cad_geometry_error"
    ASSEMBLY_MATE_ERROR = "assembly_mate_error"
    DRAWING_ERROR = "drawing_error"
    GATEWAY_API_ERROR = "gateway_api_error"
    VISUAL_UNCERTAINTY = "visual_uncertainty"
    UNRESOLVED_REQUIREMENT = "unresolved_requirement"


class RunState(StrEnum):
    INTAKE = "INTAKE"
    ANALYSIS_PLANNING = "ANALYSIS_PLANNING"
    CAD_PLANNING = "CAD_PLANNING"
    CAD_EXECUTION = "CAD_EXECUTION"
    DRAWING_PLANNING = "DRAWING_PLANNING"
    VISUAL_QA = "VISUAL_QA"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    FINAL_REVIEW = "FINAL_REVIEW"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


class ValueStatus(StrEnum):
    KNOWN = "KNOWN"
    ASSUMPTION = "ASSUMPTION"
    UNKNOWN = "UNKNOWN"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"


class ArtifactRef(StrictModel):
    artifact_id: str = Field(min_length=1)
    artifact_type: ArtifactType
    run_id: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    input_hashes: list[str] = Field(default_factory=list)
    content_hash: str = Field(min_length=1)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING


class DesignValue(StrictModel):
    value: int | float | None
    unit: str = Field(min_length=1)
    status: ValueStatus
    approved: bool = False


class CadAction(StrictModel):
    action_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    semantic_id: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(StrictModel):
    schema_version: str = "1.0"
    plan_id: str = Field(min_length=1)
    approved_design_hash: str = Field(min_length=1)
    target_scope: Literal["sandbox", "onshape"]
    execution_mode: ExecutionMode = ExecutionMode.SIMULATED
    onshape_scope: OnshapeScope | None = None
    assumptions: list[DesignValue] = Field(default_factory=list)
    actions: list[CadAction]


class GatewayReport(StrictModel):
    plan_id: str
    status: Literal["DENIED", "EXECUTED", "FAILED"]
    code: str
    reason: str
    network_request_sent: bool
    execution_mode: ExecutionMode = ExecutionMode.SIMULATED
    transport_name: str = Field(default="unknown", min_length=1)
    readback_verified: bool = False
    executed_action_ids: list[str] = Field(default_factory=list)
    receipts: list[TransportReceipt] = Field(default_factory=list)


class Diagnosis(StrictModel):
    issue_type: IssueType
    repair_target: str | None
    next_state: RunState
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)


class DrawingView(StrictModel):
    view_id: str = Field(min_length=1)
    orientation: Literal["front", "top", "right", "isometric"]
    scale: float = Field(default=1.0, gt=0)


class DrawingPlan(StrictModel):
    schema_version: str = "1.0"
    plan_id: str = Field(min_length=1)
    approved_design_hash: str = Field(min_length=1)
    projection: Literal["first_angle", "third_angle"] = "third_angle"
    views: list[DrawingView] = Field(min_length=1)

    @model_validator(mode="after")
    def require_three_views(self) -> DrawingPlan:
        orientations = {view.orientation for view in self.views}
        if not {"front", "top", "right"}.issubset(orientations):
            raise ValueError("drawing plan requires front, top, and right views")
        return self


class VisualIssue(StrictModel):
    issue_id: str = Field(min_length=1)
    issue_type: IssueType
    severity: Literal["info", "warning", "error"]
    confidence: float = Field(ge=0, le=1)
    observed_in: list[str] = Field(min_length=1)
    related_semantic_ids: list[str] = Field(default_factory=list)


class VisualReport(StrictModel):
    schema_version: str = "1.0"
    report_id: str = Field(min_length=1)
    mode: Literal["simulated", "observed"]
    cad_spec_artifact_id: str = Field(min_length=1)
    cad_render_artifacts: list[str] = Field(default_factory=list)
    drawing_render_artifacts: list[str] = Field(default_factory=list)
    issues: list[VisualIssue] = Field(default_factory=list)


class TaskNode(StrictModel):
    id: str = Field(min_length=1)
    capability: Capability
    model_profile: str | None = None
    executor: str | None = None
    input_artifacts: list[str] = Field(default_factory=list)


class TaskEdge(StrictModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class TaskGraph(StrictModel):
    schema_version: str = "1.0"
    run_id: str = Field(min_length=1)
    nodes: list[TaskNode] = Field(min_length=1)
    edges: list[TaskEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> TaskGraph:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("task graph contains duplicate node IDs")

        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("task graph edge references a missing node")

        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        indegree = {node_id: 0 for node_id in node_ids}
        for edge in self.edges:
            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1

        queue = [node_id for node_id, degree in indegree.items() if degree == 0]
        visited = 0
        while queue:
            current = queue.pop()
            visited += 1
            for target in adjacency[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if visited != len(node_ids):
            raise ValueError("task graph contains a cycle")
        return self


JsonObject = dict[str, Any]
