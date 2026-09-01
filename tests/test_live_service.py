from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import onshape_agent.live_service as live_service
from onshape_agent.contracts import TransportReceipt
from onshape_agent.live_service import (
    LIVE_MCP_COMMAND,
    LiveService,
    inspect_local_auth,
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, object]


class FakeSession:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[ToolCall] = []
        self.closed = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True

    def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append(ToolCall(name, arguments))
        response = self.responses.get(name)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.calls = 0

    def __call__(self) -> FakeSession:
        self.calls += 1
        return self.session


def test_open_session_uses_the_pinned_windows_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    class FakeMcpSession:
        def __init__(self, command: list[str], **_: object) -> None:
            seen.append(command)

    monkeypatch.setattr(live_service, "McpStdioSession", FakeMcpSession)

    live_service.open_session()

    assert seen == [list(LIVE_MCP_COMMAND)]
    assert LIVE_MCP_COMMAND == ("npx.cmd", "--yes", "onshape-mcp@0.5.2")


def test_auth_status_validates_existing_session_without_login() -> None:
    session = FakeSession({"onshape_auth_status": {"authenticated": True}})
    factory = FakeSessionFactory(session)

    receipt = LiveService(session_factory=factory).auth_status()

    assert receipt == TransportReceipt(
        operation="auth_status",
        status="SUCCEEDED",
        network_request_sent=True,
        readback_verified=True,
        evidence_summary={"response_present": True},
    )
    assert session.calls == [
        ToolCall("onshape_auth_status", {"validate": True})
    ]
    assert factory.calls == 1
    assert session.closed is True


def test_auth_status_maps_missing_login_to_auth_required() -> None:
    session = FakeSession({"onshape_auth_status": {"status": "invalid"}})

    receipt = LiveService(session_factory=FakeSessionFactory(session)).auth_status()

    assert receipt.status == "FAILED"
    assert receipt.error_code == "AUTH_REQUIRED"
    assert receipt.network_request_sent is True
    assert receipt.readback_verified is False


def test_list_documents_enforces_bounded_limit_and_returns_safe_receipt() -> None:
    session = FakeSession(
        {
            "onshape_api_call": {
                "items": [
                    {
                        "id": "doc-123",
                        "owner": {"email": "private@example.com"},
                        "description": "private-body",
                    }
                ]
            }
        }
    )
    service = LiveService(session_factory=FakeSessionFactory(session))

    receipt = service.list_documents(1)

    assert receipt.status == "SUCCEEDED"
    assert receipt.evidence_summary == {"item_count": 1}
    assert session.calls == [
        ToolCall(
            "onshape_api_call",
            {"endpoint": "getDocuments", "query_params": {"limit": "1"}},
        )
    ]
    assert "private@example.com" not in receipt.model_dump_json()
    assert "private-body" not in receipt.model_dump_json()

    with pytest.raises(ValueError, match="limit"):
        service.list_documents(101)


def test_read_document_binds_document_id_and_returns_no_raw_payload() -> None:
    session = FakeSession(
        {
            "onshape_api_call": {
                "id": "doc-123",
                "owner": {"email": "private@example.com"},
                "description": "private-body",
            }
        }
    )

    receipt = LiveService(session_factory=FakeSessionFactory(session)).read_document(
        "doc-123"
    )

    assert receipt.operation == "get_document"
    assert receipt.status == "SUCCEEDED"
    assert receipt.evidence_summary == {"document_id_matches": True}
    assert session.calls == [
        ToolCall(
            "onshape_api_call",
            {"endpoint": "getDocument", "path_params": {"did": "doc-123"}},
        )
    ]
    output = receipt.model_dump_json()
    assert "private@example.com" not in output
    assert "private-body" not in output


def test_local_auth_inspection_checks_presence_without_reading_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "onshape-mcp"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    tokens_path = config_dir / "tokens.json"
    config_path.write_text('client_secret = "private-config"', encoding="utf-8")
    tokens_path.write_text('{"access_token":"private-token"}', encoding="utf-8")

    def fail_if_read(*_: object, **__: object) -> str:
        raise AssertionError("local auth inspection must not read config values")

    monkeypatch.setattr(Path, "read_text", fail_if_read)

    summary = inspect_local_auth(config_root=config_dir)

    assert summary.config_present is True
    assert summary.tokens_present is True
    assert summary.configured is True
    assert summary.network_request_sent is False
    assert summary.credential_values_read is False
    assert "private-config" not in summary.model_dump_json()
    assert "private-token" not in summary.model_dump_json()
