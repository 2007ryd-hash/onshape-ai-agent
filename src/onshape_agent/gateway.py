"""Deterministic CAD Gateway with an injected transport boundary."""

from __future__ import annotations

from typing import Protocol

from .contracts import CadAction, ExecutionPlan, GatewayReport
from .policy import PolicyDenied, validate_and_order


class CadTransport(Protocol):
    sends_network: bool

    def dispatch(self, action: CadAction) -> dict[str, object]: ...


class RecordingTransport:
    """Network-free transport used by V1 tests and demonstrations."""

    sends_network = False

    def __init__(self) -> None:
        self.calls: list[CadAction] = []

    def dispatch(self, action: CadAction) -> dict[str, object]:
        self.calls.append(action)
        return {"status": "RECORDED", "action_id": action.action_id}


class CadGateway:
    def __init__(self, transport: CadTransport) -> None:
        self._transport = transport

    def execute(self, plan: ExecutionPlan) -> GatewayReport:
        try:
            ordered = validate_and_order(plan)
        except PolicyDenied as error:
            return GatewayReport(
                plan_id=plan.plan_id,
                status="DENIED",
                code=error.code,
                reason=error.reason,
                network_request_sent=False,
            )

        executed: list[str] = []
        for action in ordered:
            self._transport.dispatch(action)
            executed.append(action.action_id)
        return GatewayReport(
            plan_id=plan.plan_id,
            status="EXECUTED",
            code="PLAN_EXECUTED",
            reason="All actions passed policy and were dispatched in dependency order.",
            network_request_sent=bool(ordered) and self._transport.sends_network,
            executed_action_ids=executed,
        )
