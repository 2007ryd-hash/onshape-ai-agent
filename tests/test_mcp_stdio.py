from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from onshape_agent.mcp_stdio import (
    MCP_PROTOCOL_VERSION,
    McpStdioSession,
    McpTransportError,
)

FAKE_SERVER = Path(__file__).with_name("fake_mcp_server.py")


@pytest.mark.parametrize(
    "result",
    [
        {"isError": True, "structuredContent": {"items": []}},
        {
            "isError": True,
            "content": [{"type": "text", "text": '{"items":[]}'}],
        },
    ],
)
def test_tool_error_cannot_decode_as_success(result: dict[str, object]) -> None:
    with pytest.raises(McpTransportError) as raised:
        McpStdioSession._decode_tool_result(result)

    assert raised.value.code == "MCP_ERROR"
    assert raised.value.network_request_sent is True


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        ("API error (HTTP 401): private-body", "AUTH_REQUIRED"),
        ("API error (HTTP 403): private-body", "SCOPE_DENIED"),
        ("API error (HTTP 404): private-body", "NOT_FOUND"),
        ("API error (HTTP 429): private-body", "RATE_LIMITED"),
        ("API error (HTTP 500): private-body HTTP 401", "MCP_ERROR"),
        ("private-body: API error (HTTP 403): denied", "MCP_ERROR"),
        ('{"status": 401, "message": "private-body"}', "MCP_ERROR"),
    ],
)
def test_tool_error_maps_only_pinned_http_prefix(
    text: str, expected_code: str
) -> None:
    result = {"isError": True, "content": [{"type": "text", "text": text}]}

    with pytest.raises(McpTransportError) as raised:
        McpStdioSession._decode_tool_result(result)

    assert raised.value.code == expected_code
    assert str(raised.value) == expected_code
    assert raised.value.network_request_sent is True


@pytest.fixture
def fake_mcp_command() -> list[str]:
    return [sys.executable, str(FAKE_SERVER)]


def command_for(
    fake_mcp_command: list[str], scenario: str, trace_path: Path, *extra: str
) -> list[str]:
    return [
        *fake_mcp_command,
        "--scenario",
        scenario,
        "--trace",
        str(trace_path),
        *extra,
    ]


def read_trace(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def wait_for_path(path: Path, timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path.name}")


def wait_for_tool_call(
    path: Path, tool_name: str, timeout_seconds: float = 2.0
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            messages = read_trace(path)
            if any(
                message.get("method") == "tools/call"
                and message.get("params", {}).get("name") == tool_name
                for message in messages
            ):
                return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {tool_name}")


def pid_is_running(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        check=False,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return re.search(rf"\b{pid}\b", result.stdout) is not None


def wait_for_pid_exit(pid: int, timeout_seconds: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pid_is_running(pid):
            return True
        time.sleep(0.05)
    return not pid_is_running(pid)


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


def test_concurrent_tool_calls_are_serialized(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    command = command_for(fake_mcp_command, "concurrent", trace_path)

    with McpStdioSession(command, timeout_seconds=2) as session:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(session.call_tool, "first", {})
            wait_for_tool_call(trace_path, "first")
            second = executor.submit(session.call_tool, "second", {})

            assert first.result(timeout=2) == {"tool": "first"}
            assert second.result(timeout=2) == {"tool": "second"}


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


def test_stdout_queue_overflow_is_sanitized_and_terminates_child(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    marker_path = tmp_path / "flood.marker"
    command = command_for(
        fake_mcp_command,
        "queue-flood",
        trace_path,
        "--marker",
        str(marker_path),
    )
    session = McpStdioSession(
        command, timeout_seconds=2, max_queue_size=2
    )

    try:
        session.__enter__()
        process = session.process
        assert process is not None
        wait_for_path(marker_path)

        with pytest.raises(McpTransportError, match="RESPONSE_QUEUE_FULL") as raised:
            session.call_tool("queue_flood", {})

        assert process.poll() is not None
        assert "fake-child-secret" not in str(raised.value)
    finally:
        session.close()


def test_timeout_raises_sanitized_error_and_terminates_child(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "hang", tmp_path / "trace.jsonl")
    session = McpStdioSession(command, timeout_seconds=0.1)

    with pytest.raises(McpTransportError, match="TRANSPORT_TIMEOUT") as raised:
        with session:
            process = session.process
            assert process is not None
            session.call_tool("hang", {})

    assert raised.value.network_request_sent is True
    assert process.poll() is not None


def test_mcp_error_tracks_network_request_state() -> None:
    before_write = McpTransportError(
        "TRANSPORT_FAILED", network_request_sent=False
    )
    after_write = McpTransportError("TRANSPORT_TIMEOUT", network_request_sent=True)

    assert before_write.network_request_sent is False
    assert after_write.network_request_sent is True


def test_write_failure_before_stdin_write_marks_request_unsent() -> None:
    class FailingStdin:
        def write(self, _: bytes) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            raise AssertionError("flush must not run after write failure")

    class RunningProcess:
        stdin = FailingStdin()

        @staticmethod
        def poll() -> None:
            return None

    session = McpStdioSession([sys.executable])
    session._process = RunningProcess()  # type: ignore[assignment]
    session._initialized = True

    with pytest.raises(McpTransportError, match="TRANSPORT_FAILED") as raised:
        session.call_tool("tool", {})

    assert raised.value.network_request_sent is False


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
    command_name = "definitely-missing-onshape-mcp-executable"
    with pytest.raises(McpTransportError, match="TRANSPORT_UNAVAILABLE") as raised:
        with McpStdioSession([command_name]):
            pass

    assert raised.value.network_request_sent is False
    assert command_name not in str(raised.value)


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": -1},
        {"timeout_seconds": math.inf},
        {"timeout_seconds": math.nan},
        {"max_response_bytes": 0},
        {"max_queue_size": 0},
    ],
)
def test_session_rejects_invalid_limits(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        McpStdioSession([sys.executable], **kwargs)


def test_initialize_failure_closes_child(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "init-error", tmp_path / "trace.jsonl")
    session = McpStdioSession(command, timeout_seconds=2)

    with pytest.raises(McpTransportError, match="TRANSPORT_UNAVAILABLE"):
        session.__enter__()

    process = session.process
    assert process is not None
    assert process.poll() is not None
    session.close()


def test_unexpected_initialize_failure_closes_child(
    fake_mcp_command: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = command_for(fake_mcp_command, "normal", tmp_path / "trace.jsonl")
    session = McpStdioSession(command, timeout_seconds=2)

    def fail_initialize() -> None:
        raise RuntimeError("initialization failed")

    monkeypatch.setattr(session, "_initialize", fail_initialize)

    with pytest.raises(RuntimeError, match="initialization failed"):
        session.__enter__()

    process = session.process
    assert process is not None
    assert process.poll() is not None
    session.close()


def test_reenter_fails_without_replacing_running_process(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    command = command_for(fake_mcp_command, "normal", tmp_path / "trace.jsonl")
    session = McpStdioSession(command, timeout_seconds=2)
    session.__enter__()
    process = session.process
    assert process is not None

    try:
        with pytest.raises(McpTransportError, match="TRANSPORT_FAILED"):
            session.__enter__()
        assert session.process is process
        assert process.poll() is None
    finally:
        session.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=2)


@pytest.mark.skipif(os.name != "nt", reason="Windows process trees only")
def test_close_terminates_windows_process_tree(
    fake_mcp_command: list[str], tmp_path: Path
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    child_pid_path = tmp_path / "child.pid"
    command = command_for(
        fake_mcp_command,
        "spawn-child",
        trace_path,
        "--child-pid-file",
        str(child_pid_path),
    )
    session = McpStdioSession(command, timeout_seconds=2)
    child_pid: int | None = None

    try:
        session.__enter__()
        process = session.process
        assert process is not None
        wait_for_path(child_pid_path)
        child_pid = int(child_pid_path.read_text(encoding="ascii"))
        assert pid_is_running(child_pid)
    finally:
        session.close()

    assert child_pid is not None
    tree_exited = wait_for_pid_exit(child_pid)
    if not tree_exited:
        subprocess.run(
            ["taskkill", "/PID", str(child_pid), "/T", "/F"],
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    assert tree_exited
