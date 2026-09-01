"""Deterministic CAD Gateway with an injected transport boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .contracts import (
    CadAction,
    ExecutionMode,
    ExecutionPlan,
    GatewayReport,
    TransportReceipt,
)
from .live_transport import LivePolicyDenied
from .policy import PolicyDenied, validate_and_order


class CadTransport(Protocol):
    transport_name: str

    def preflight(self, actions: Sequence[CadAction]) -> None: ...

    def dispatch(self, action: CadAction) -> TransportReceipt: ...


class RecordingTransport:
    """Network-free transport used by V1 tests and demonstrations."""

    transport_name = "recording"

    def __init__(self) -> None:
        self.calls: list[CadAction] = []

    def preflight(self, actions: Sequence[CadAction]) -> None:
        """Accept the already policy-checked offline actions."""

    def dispatch(self, action: CadAction) -> TransportReceipt:
        self.calls.append(action)
        return TransportReceipt(
            operation=action.type,
            status="SUCCEEDED",
            network_request_sent=False,
            readback_verified=True,
            evidence_summary={"action_id": action.action_id},
        )


class CadGateway:
    def __init__(self, transport: CadTransport) -> None:
        self._transport = transport

    def execute(self, plan: ExecutionPlan) -> GatewayReport:
        transport_name = _transport_name(self._transport)
        try:
            ordered = validate_and_order(plan)
        except (PolicyDenied, LivePolicyDenied) as error:
            return _denied_report(plan, error.code, error.reason, transport_name)

        try:
            self._transport.preflight(ordered)
        except (PolicyDenied, LivePolicyDenied) as error:
            return _denied_report(plan, error.code, error.reason, transport_name)
        except Exception as error:
            return _failed_report(
                plan,
                _transport_error_code(error),
                transport_name=transport_name,
                reason="Transport preflight failed before dispatch.",
            )

        executed: list[str] = []
        receipts: list[TransportReceipt] = []
        for action in ordered:
            try:
                receipt = self._transport.dispatch(action)
            except (PolicyDenied, LivePolicyDenied) as error:
                return _denied_report(
                    plan,
                    error.code,
                    error.reason,
                    transport_name,
                    receipts=receipts,
                    executed_action_ids=executed,
                )
            except Exception as error:
                return _failed_report(
                    plan,
                    _transport_error_code(error),
                    transport_name=transport_name,
                    receipts=receipts,
                    executed_action_ids=executed,
                    reason="Transport failed while dispatching the execution plan.",
                )

            if not isinstance(receipt, TransportReceipt):
                return _failed_report(
                    plan,
                    "TRANSPORT_FAILED",
                    transport_name=transport_name,
                    receipts=receipts,
                    executed_action_ids=executed,
                    reason="Transport returned an invalid typed receipt.",
                )

            receipts.append(receipt)
            if receipt.operation != _expected_receipt_operation(action):
                return _failed_report(
                    plan,
                    "TRANSPORT_FAILED",
                    transport_name=transport_name,
                    receipts=receipts,
                    executed_action_ids=executed,
                    reason=(
                        "Transport receipt did not identify the dispatched operation."
                    ),
                )
            if receipt.status == "FAILED":
                return _failed_report(
                    plan,
                    _receipt_error_code(receipt),
                    transport_name=transport_name,
                    receipts=receipts,
                    executed_action_ids=executed,
                    reason="Transport reported a failed operation.",
                )
            if (
                plan.execution_mode is ExecutionMode.LIVE
                and not receipt.readback_verified
            ):
                return _failed_report(
                    plan,
                    "VERIFICATION_FAILED",
                    transport_name=transport_name,
                    receipts=receipts,
                    executed_action_ids=executed,
                    reason="Live readback verification did not succeed.",
                )
            executed.append(action.action_id)

        if plan.execution_mode is ExecutionMode.LIVE and (
            not receipts
            or not any(receipt.network_request_sent for receipt in receipts)
        ):
            return _failed_report(
                plan,
                "TRANSPORT_FAILED",
                transport_name=transport_name,
                receipts=receipts,
                executed_action_ids=executed,
                reason="Live execution produced no network request receipt.",
            )

        readback_verified = bool(receipts) and all(
            receipt.readback_verified for receipt in receipts
        )
        return GatewayReport(
            plan_id=plan.plan_id,
            status="EXECUTED",
            code="PLAN_EXECUTED",
            reason="All actions passed policy and were dispatched in dependency order.",
            network_request_sent=any(
                receipt.network_request_sent for receipt in receipts
            ),
            execution_mode=plan.execution_mode,
            transport_name=transport_name,
            readback_verified=readback_verified,
            executed_action_ids=executed,
            receipts=receipts,
        )


_SAFE_TRANSPORT_CODES = frozenset(
    {
        "AUTH_REQUIRED",
        "SCOPE_DENIED",
        "NOT_FOUND",
        "RATE_LIMITED",
        "INVALID_RESPONSE",
        "TRANSPORT_UNAVAILABLE",
        "TRANSPORT_TIMEOUT",
        "TRANSPORT_FAILED",
        "RESPONSE_TOO_LARGE",
        "RESPONSE_QUEUE_FULL",
        "VERIFICATION_FAILED",
    }
)


def _transport_name(transport: CadTransport) -> str:
    value = getattr(transport, "transport_name", None)
    if isinstance(value, str) and value:
        return value
    return type(transport).__name__


def _transport_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code in _SAFE_TRANSPORT_CODES:
        return code
    return "TRANSPORT_FAILED"


def _receipt_error_code(receipt: TransportReceipt) -> str:
    if receipt.error_code in _SAFE_TRANSPORT_CODES:
        return receipt.error_code
    return "TRANSPORT_FAILED"


def _expected_receipt_operation(action: CadAction) -> str | None:
    if action.type != "read_back":
        return action.type
    read_kind = action.parameters.get("read_kind")
    return read_kind if isinstance(read_kind, str) else action.type


def _denied_report(
    plan: ExecutionPlan,
    code: str,
    reason: str,
    transport_name: str,
    *,
    receipts: list[TransportReceipt] | None = None,
    executed_action_ids: list[str] | None = None,
) -> GatewayReport:
    return GatewayReport(
        plan_id=plan.plan_id,
        status="DENIED",
        code=code,
        reason=reason or "Execution plan was denied by policy.",
        network_request_sent=_network_sent(receipts or []),
        execution_mode=plan.execution_mode,
        transport_name=transport_name,
        readback_verified=_readback_verified(receipts or []),
        executed_action_ids=list(executed_action_ids or []),
        receipts=list(receipts or []),
    )


def _failed_report(
    plan: ExecutionPlan,
    code: str,
    *,
    transport_name: str,
    receipts: list[TransportReceipt] | None = None,
    executed_action_ids: list[str] | None = None,
    reason: str,
) -> GatewayReport:
    safe_code = code if code in _SAFE_TRANSPORT_CODES else "TRANSPORT_FAILED"
    safe_receipts = list(receipts or [])
    return GatewayReport(
        plan_id=plan.plan_id,
        status="FAILED",
        code=safe_code,
        reason=reason,
        network_request_sent=_network_sent(safe_receipts),
        execution_mode=plan.execution_mode,
        transport_name=transport_name,
        readback_verified=_readback_verified(safe_receipts),
        executed_action_ids=list(executed_action_ids or []),
        receipts=safe_receipts,
    )


def _network_sent(receipts: list[TransportReceipt]) -> bool:
    return any(receipt.network_request_sent for receipt in receipts)


def _readback_verified(receipts: list[TransportReceipt]) -> bool:
    return bool(receipts) and all(receipt.readback_verified for receipt in receipts)
