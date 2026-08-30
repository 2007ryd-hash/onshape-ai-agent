"""Fail-closed policy checks for model-proposed CAD plans."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import CadAction, ExecutionPlan, ValueStatus

ALLOWED_OPERATIONS = frozenset(
    {
        "ensure_document",
        "ensure_part_studio",
        "ensure_sketch",
        "ensure_extrude",
        "ensure_hole",
        "ensure_fillet",
        "ensure_pattern",
        "ensure_assembly",
        "ensure_instance",
        "ensure_mate",
        "ensure_drawing",
        "render_view",
        "export_artifact",
        "read_back",
    }
)


@dataclass(frozen=True, slots=True)
class PolicyDenied(Exception):
    code: str
    reason: str


def validate_and_order(plan: ExecutionPlan) -> list[CadAction]:
    """Validate an entire plan before returning a dependency-safe order."""

    for assumption in plan.assumptions:
        if assumption.status is ValueStatus.ASSUMPTION and not assumption.approved:
            raise PolicyDenied(
                "UNAPPROVED_ASSUMPTION",
                "An assumption must be approved before CAD execution.",
            )

    for action in plan.actions:
        if action.type not in ALLOWED_OPERATIONS:
            raise PolicyDenied(
                "OPERATION_NOT_ALLOWED",
                f"{action.type} is not in the V1 operation allowlist.",
            )

    by_id = {action.action_id: action for action in plan.actions}
    if len(by_id) != len(plan.actions):
        raise PolicyDenied("DUPLICATE_ACTION_ID", "Action IDs must be unique.")

    indegree = {action_id: 0 for action_id in by_id}
    dependents: dict[str, list[str]] = {action_id: [] for action_id in by_id}
    for action in plan.actions:
        for dependency in action.depends_on:
            if dependency not in by_id:
                raise PolicyDenied(
                    "UNKNOWN_DEPENDENCY",
                    (
                        f"Action {action.action_id} depends on unknown action "
                        f"{dependency}."
                    ),
                )
            indegree[action.action_id] += 1
            dependents[dependency].append(action.action_id)

    queue = sorted(action_id for action_id, degree in indegree.items() if degree == 0)
    ordered: list[CadAction] = []
    while queue:
        action_id = queue.pop(0)
        ordered.append(by_id[action_id])
        for dependent in sorted(dependents[action_id]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
                queue.sort()

    if len(ordered) != len(plan.actions):
        raise PolicyDenied("ACTION_CYCLE", "Action dependencies contain a cycle.")
    return ordered
