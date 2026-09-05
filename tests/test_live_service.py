from __future__ import annotations

import hashlib
import json
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


@pytest.fixture(autouse=True)
def isolated_run_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


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
    assert session.calls == [ToolCall("onshape_auth_status", {"validate": True})]
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
    assert summary.authenticated is None
    assert summary.verification == "unverified"
    assert summary.network_request_sent is False
    assert summary.credential_values_read is False
    assert "private-config" not in summary.model_dump_json()
    assert "private-token" not in summary.model_dump_json()


def test_windows_local_auth_uses_distinct_upstream_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_service.sys, "platform", "win32")
    monkeypatch.delenv("ONSHAPE_MCP_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    for name, dirname, filename in (
        ("APPDATA", "roaming", "config.toml"),
        ("LOCALAPPDATA", "local", "tokens.json"),
    ):
        base = tmp_path / dirname
        root = base / "onshape-mcp"
        root.mkdir(parents=True)
        (root / filename).touch()
        monkeypatch.setenv(name, str(base))
    status = inspect_local_auth()
    assert status.config_present and status.tokens_present
    assert status.authenticated is None
    assert status.verification == "unverified"


@pytest.mark.parametrize("absolute", [True, False])
def test_xdg_only_accepts_absolute_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    absolute: bool,
) -> None:
    monkeypatch.setattr(live_service.sys, "platform", "win32")
    monkeypatch.delenv("ONSHAPE_MCP_CONFIG_DIR", raising=False)
    for xdg, fallback, filename in (
        ("XDG_CONFIG_HOME", "APPDATA", "config.toml"),
        ("XDG_DATA_HOME", "LOCALAPPDATA", "tokens.json"),
    ):
        base = tmp_path / xdg
        (base / "onshape-mcp").mkdir(parents=True)
        (base / "onshape-mcp" / filename).touch()
        monkeypatch.setenv(xdg, str(base) if absolute else "relative")
        monkeypatch.setenv(fallback, str(tmp_path / "missing"))
    status = inspect_local_auth()
    assert status.config_present is absolute
    assert status.tokens_present is absolute


def test_local_auth_does_not_guess_token_names(tmp_path: Path) -> None:
    (tmp_path / "config.toml").touch()
    for filename in ("token.json", "tokens.backup.json", "token-notes.txt"):
        (tmp_path / filename).touch()
    assert inspect_local_auth(tmp_path).tokens_present is False


def test_gateway_policy_blocks_service_before_any_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onshape_agent.gateway as gateway
    from onshape_agent.policy import PolicyDenied

    def deny(_plan: object) -> object:
        raise PolicyDenied("SCOPE_DENIED", "test scope denied")

    monkeypatch.setattr(gateway, "validate_and_order", deny)
    session = FakeSession({"onshape_api_call": {"items": []}})
    receipt = LiveService(session_factory=lambda: session).list_documents()
    assert receipt.status == "FAILED"
    assert receipt.error_code == "SCOPE_DENIED"
    assert receipt.network_request_sent is False
    assert session.calls == []


def test_live_run_persists_gateway_summary_and_verifiable_hash(tmp_path: Path) -> None:
    session = FakeSession(
        {
            "onshape_api_call": {
                "items": [{"id": "doc-123", "description": "private-response-body"}]
            }
        }
    )
    service = LiveService(
        session_factory=lambda: session, output_root=tmp_path / "audit"
    )
    receipt = service.list_documents()
    (run_dir,) = (tmp_path / "audit").iterdir()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    execution = manifest["execution"]
    assert execution["execution_mode"] == "live"
    assert execution["network_request_sent"] is True
    assert execution["readback_verified"] is True
    document = json.loads(
        (run_dir / "artifacts" / "live_execution_report.json").read_text(
            encoding="utf-8"
        )
    )
    report = document["payload"]
    assert report["status"] == "EXECUTED"
    assert report["receipts"] == [receipt.model_dump(mode="json")]
    digest = hashlib.sha256(
        json.dumps(
            report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert document["metadata"]["content_hash"] == f"sha256:{digest}"
    assert execution["artifacts"][0]["content_hash"] == f"sha256:{digest}"
    assert "private-response-body" not in "".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.rglob("*")
        if path.is_file()
    )


def test_failed_session_is_audited_without_exception_contents(tmp_path: Path) -> None:
    def unavailable() -> object:
        raise FileNotFoundError("private-command-path")

    service = LiveService(session_factory=unavailable, output_root=tmp_path / "audit")
    receipt = service.auth_status()
    assert receipt.error_code == "TRANSPORT_UNAVAILABLE"
    assert receipt.network_request_sent is False
    (run_dir,) = (tmp_path / "audit").iterdir()
    output = "".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    assert "private-command-path" not in output
    assert "TRANSPORT_UNAVAILABLE" in output
