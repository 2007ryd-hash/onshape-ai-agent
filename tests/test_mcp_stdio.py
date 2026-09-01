from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from onshape_agent.mcp_stdio import (
    MCP_PROTOCOL_VERSION,
    McpStdioSession,
    McpTransportError,
)

FAKE_SERVER = Path(__file__).with_name("fake_mcp_server.py")


@pytest.fixture
def fake_mcp_command() -> list[str]:
    return [sys.executable, str(FAKE_SERVER)]


def command_for(
    fake_mcp_command: list[str], scenario: str, trace_path: Path
) -> list[str]:
    return [
        *fake_mcp_command,
        "--scenario",
        scenario,
        "--trace",
        str(trace_path),
    ]


def read_trace(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_session_initializes_then_calls_tool(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    command = command_for(fake_mcp_command, "normal", trace_path)

    with McpStdioSession(command, timeout_seconds=2) as session:
        result = session.call_tool("onshape_auth_status", {"validate": False})

    assert result == {"configured": True}
    messages = read_trace(trace_path)
    assert [message["method"] for message in messages] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert messages[0]["id"] == 1
    assert messages[0]["params"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert "id" not in messages[1]
    assert messages[2]["id"] == 2
    assert messages[2]["params"] == {
        "name": "onshape_auth_status",
        "arguments": {"validate": False},
    }


def test_request_ids_are_monotonic_across_tool_calls(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    command = command_for(fake_mcp_command, "normal", trace_path)

    with McpStdioSession(command, timeout_seconds=2) as session:
        session.call_tool("first", {})
        session.call_tool("second", {})

    messages = read_trace(trace_path)
    assert [message.get("id") for message in messages] == [1, None, 2, 3]


def test_structured_content_has_priority_over_text_content(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "structured", tmp_path / "trace.jsonl")

    with McpStdioSession(command, timeout_seconds=2) as session:
        result = session.call_tool("structured", {})

    assert result == {"source": "structured", "value": 7}


def test_single_json_text_content_is_decoded(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "normal", tmp_path / "trace.jsonl")

    with McpStdioSession(command, timeout_seconds=2) as session:
        result = session.call_tool("onshape_auth_status", {})

    assert result == {"configured": True}


def test_multiple_content_blocks_are_invalid_response(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "multi-content", tmp_path / "trace.jsonl")

    with (
        McpStdioSession(command, timeout_seconds=2) as session,
        pytest.raises(McpTransportError, match="INVALID_RESPONSE") as raised,
    ):
        session.call_tool("multi_content", {})

    assert "fake-child-secret" not in str(raised.value)


def test_non_text_content_is_invalid_response(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "non-text", tmp_path / "trace.jsonl")

    with (
        McpStdioSession(command, timeout_seconds=2) as session,
        pytest.raises(McpTransportError, match="INVALID_RESPONSE"),
    ):
        session.call_tool("non_text", {})


def test_json_rpc_error_is_generic_and_does_not_leak_response(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "rpc-error", tmp_path / "trace.jsonl")

    with (
        McpStdioSession(command, timeout_seconds=2) as session,
        pytest.raises(McpTransportError, match="MCP_ERROR") as raised,
    ):
        session.call_tool("rpc_error", {})

    assert "fake-child-secret" not in str(raised.value)


def test_malformed_response_is_sanitized(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "malformed", tmp_path / "trace.jsonl")

    with (
        McpStdioSession(command, timeout_seconds=2) as session,
        pytest.raises(McpTransportError, match="INVALID_RESPONSE") as raised,
    ):
        session.call_tool("malformed", {})

    assert "fake-child-secret" not in str(raised.value)


def test_oversized_response_is_rejected_and_terminates_child(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "oversized", tmp_path / "trace.jsonl")
    session = McpStdioSession(
        command, timeout_seconds=2, max_response_bytes=256
    )

    try:
        session.__enter__()
        process = session.process
        assert process is not None

        with pytest.raises(McpTransportError, match="RESPONSE_TOO_LARGE") as raised:
            session.call_tool("oversized", {})

        assert process.poll() is not None
        assert "fake-child-secret" not in str(raised.value)
    finally:
        session.close()


def test_stderr_is_drained_while_waiting_for_response(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "stderr-flood", tmp_path / "trace.jsonl")

    with McpStdioSession(command, timeout_seconds=3) as session:
        result = session.call_tool("stderr_flood", {})

    assert result == {"configured": True}


def test_timeout_raises_sanitized_error_and_terminates_child(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "hang", tmp_path / "trace.jsonl")
    session = McpStdioSession(command, timeout_seconds=0.1)

    with pytest.raises(McpTransportError, match="TRANSPORT_TIMEOUT"):
        with session:
            process = session.process
            assert process is not None
            session.call_tool("hang", {})

    assert process.poll() is not None


def test_close_is_idempotent_and_cleans_up_process(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "normal", tmp_path / "trace.jsonl")
    session = McpStdioSession(command, timeout_seconds=2)
    session.__enter__()
    process = session.process
    assert process is not None

    session.close()
    session.close()

    assert process.poll() is not None


def test_process_exit_is_reported_without_child_output(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "exit", tmp_path / "trace.jsonl")

    with (
        McpStdioSession(command, timeout_seconds=2) as session,
        pytest.raises(McpTransportError, match="TRANSPORT_FAILED") as raised,
    ):
        session.call_tool("exit", {})

    assert "fake-child-secret" not in str(raised.value)


def test_missing_child_is_transport_unavailable() -> None:
    with pytest.raises(McpTransportError, match="TRANSPORT_UNAVAILABLE") as raised:
        with McpStdioSession([sys.executable, "does-not-exist-fake-server.py"]):
            pass

    assert "does-not-exist" not in str(raised.value)


def test_response_id_mismatch_is_invalid_response(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "wrong-id", tmp_path / "trace.jsonl")

    with (
        McpStdioSession(command, timeout_seconds=2) as session,
        pytest.raises(McpTransportError, match="INVALID_RESPONSE"),
    ):
        session.call_tool("wrong_id", {})


def test_inbound_server_request_is_rejected_as_invalid_response(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(
        fake_mcp_command, "server-request", tmp_path / "trace.jsonl"
    )

    with (
        McpStdioSession(command, timeout_seconds=2) as session,
        pytest.raises(McpTransportError, match="INVALID_RESPONSE") as raised,
    ):
        session.call_tool("server_request", {})

    assert "fake-child-secret" not in str(raised.value)
