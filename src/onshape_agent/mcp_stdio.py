"""Small, bounded JSON-RPC client for an MCP server connected over stdio."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from queue import Empty, Queue
from typing import Any, BinaryIO

MCP_PROTOCOL_VERSION = "2025-06-18"
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024

_EOF = object()
_OVERSIZED = object()


class McpTransportError(RuntimeError):
    """An MCP transport failure represented only by a stable public code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class McpStdioSession:
    """Manage one MCP child process and its newline-delimited JSON-RPC stream."""

    def __init__(
        self,
        command: Sequence[str | Path],
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive integer")
        self._command = [str(part) for part in command]
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_queue: Queue[bytes | object] = Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._next_id = 1
        self._initialized = False
        self._closed = False

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        """Expose the child handle for deterministic lifecycle assertions."""

        return self._process

    def __enter__(self) -> "McpStdioSession":
        if self._closed:
            raise McpTransportError("TRANSPORT_FAILED")

        self._start_process()
        try:
            self._initialize()
        except McpTransportError:
            self.close()
            raise
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def call_tool(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> object:
        """Call one tool and return its structured result or JSON text fallback."""

        if not self._initialized or self._closed:
            raise McpTransportError("TRANSPORT_FAILED")
        if not isinstance(tool_name, str) or not isinstance(arguments, Mapping):
            raise McpTransportError("INVALID_REQUEST")

        request_id = self._allocate_id()
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": dict(arguments)},
            }
        )
        result = self._read_rpc_result(request_id)
        return self._decode_tool_result(result)

    def close(self) -> None:
        """Close the pipes and terminate the child; repeated calls are harmless."""

        if self._closed:
            return
        self._closed = True

        process = self._process
        if process is None:
            return

        if process.stdin is not None:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass

        self._terminate_process()

        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass

        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is not None:
                thread.join(timeout=0.5)

    def _start_process(self) -> None:
        try:
            process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                bufsize=0,
            )
        except (OSError, ValueError):
            raise McpTransportError("TRANSPORT_UNAVAILABLE") from None

        self._process = process
        assert process.stdout is not None
        assert process.stderr is not None
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            args=(
                process.stdout,
                self._stdout_queue,
                self._max_response_bytes,
            ),
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process.stderr,),
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _initialize(self) -> None:
        request_id = self._allocate_id()
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "onshape-agent",
                        "version": "1.11.0",
                    },
                },
            }
        )
        try:
            result = self._read_rpc_result(request_id)
        except McpTransportError:
            raise McpTransportError("TRANSPORT_UNAVAILABLE") from None

        if result.get("protocolVersion") != MCP_PROTOCOL_VERSION:
            raise McpTransportError("TRANSPORT_UNAVAILABLE")

        self._send(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        self._initialized = True

    def _allocate_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _send(self, message: dict[str, object]) -> None:
        process = self._process
        if self._closed or process is None or process.stdin is None:
            raise McpTransportError("TRANSPORT_FAILED")
        if process.poll() is not None:
            raise McpTransportError("TRANSPORT_FAILED")

        try:
            encoded = json.dumps(
                message, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise McpTransportError("INVALID_REQUEST") from None

        try:
            process.stdin.write(encoded + b"\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            raise McpTransportError("TRANSPORT_FAILED") from None

    def _read_rpc_result(self, expected_id: int) -> dict[str, Any]:
        try:
            raw_line = self._stdout_queue.get(timeout=self._timeout_seconds)
        except Empty:
            self._terminate_process()
            raise McpTransportError("TRANSPORT_TIMEOUT") from None

        if raw_line is _OVERSIZED:
            self._terminate_process()
            raise McpTransportError("RESPONSE_TOO_LARGE")
        if raw_line is _EOF or not isinstance(raw_line, bytes):
            raise McpTransportError("TRANSPORT_FAILED")

        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise McpTransportError("INVALID_RESPONSE") from None

        if not isinstance(payload, dict):
            raise McpTransportError("INVALID_RESPONSE")
        if payload.get("jsonrpc") != "2.0":
            raise McpTransportError("INVALID_RESPONSE")
        if "method" in payload:
            raise McpTransportError("INVALID_RESPONSE")
        response_id = payload.get("id")
        if type(response_id) is not type(expected_id) or response_id != expected_id:
            raise McpTransportError("INVALID_RESPONSE")
        if "error" in payload:
            raise McpTransportError("MCP_ERROR")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise McpTransportError("INVALID_RESPONSE")
        return result

    @staticmethod
    def _decode_tool_result(result: dict[str, Any]) -> object:
        if "structuredContent" in result:
            return result["structuredContent"]

        content = result.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise McpTransportError("INVALID_RESPONSE")
        block = content[0]
        if not isinstance(block, dict) or block.get("type") != "text":
            raise McpTransportError("INVALID_RESPONSE")
        text = block.get("text")
        if not isinstance(text, str):
            raise McpTransportError("INVALID_RESPONSE")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise McpTransportError("INVALID_RESPONSE") from None

    @staticmethod
    def _read_stdout(
        stream: BinaryIO,
        output: Queue[bytes | object],
        max_response_bytes: int,
    ) -> None:
        try:
            while True:
                line = stream.readline(max_response_bytes + 1)
                if not line:
                    break
                if len(line) > max_response_bytes:
                    output.put(_OVERSIZED)
                    return
                output.put(line)
        except (OSError, ValueError):
            pass
        finally:
            output.put(_EOF)

    @staticmethod
    def _drain_stderr(stream: BinaryIO) -> None:
        try:
            while stream.read(4096):
                pass
        except (OSError, ValueError):
            pass

    def _terminate_process(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return

        try:
            process.terminate()
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass
