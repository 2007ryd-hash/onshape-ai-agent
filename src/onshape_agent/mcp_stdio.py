"""Small, bounded JSON-RPC client for an MCP server connected over stdio."""

from __future__ import annotations

import json
import math
import os
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any, BinaryIO

MCP_PROTOCOL_VERSION = "2025-06-18"
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_MAX_QUEUE_SIZE = 128

_EOF = object()
_OVERSIZED = object()
_QUEUE_FULL = object()


class McpTransportError(RuntimeError):
    """An MCP transport failure represented only by a stable public code."""

    def __init__(self, code: str, network_request_sent: bool = False) -> None:
        self.code = code
        self.network_request_sent = bool(network_request_sent)
        super().__init__(code)


class McpStdioSession:
    """Manage one MCP child process and its newline-delimited JSON-RPC stream."""

    def __init__(
        self,
        command: Sequence[str | Path],
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ) -> None:
        timeout_is_valid = False
        if (
            not isinstance(timeout_seconds, bool)
            and isinstance(timeout_seconds, (int, float))
        ):
            try:
                timeout_is_valid = (
                    math.isfinite(timeout_seconds) and timeout_seconds > 0
                )
            except (OverflowError, TypeError):
                pass
        if not timeout_is_valid:
            raise ValueError("timeout_seconds must be a finite positive number")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive integer")
        if (
            isinstance(max_queue_size, bool)
            or not isinstance(max_queue_size, int)
            or max_queue_size <= 0
        ):
            raise ValueError("max_queue_size must be a positive integer")
        self._command = [str(part) for part in command]
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._request_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_queue: Queue[bytes | object] = Queue(maxsize=max_queue_size)
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
        if self._closed or self._process is not None:
            raise McpTransportError("TRANSPORT_FAILED")

        try:
            self._start_process()
            self._initialize()
        except BaseException:
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

        with self._request_lock:
            request_id = self._allocate_id()
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": dict(arguments)},
                }
            )
            result = self._read_rpc_result(
                request_id,
                network_request_sent=True,
            )
            return self._decode_tool_result(
                result,
                network_request_sent=True,
            )

    def close(self) -> None:
        """Close the pipes and terminate the child; repeated calls are harmless."""

        if self._closed:
            return
        self._closed = True

        process = self._process
        if process is None:
            return

        self._terminate_process()

        if process.stdin is not None:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass

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
        if self._closed or self._process is not None:
            raise McpTransportError("TRANSPORT_FAILED")

        popen_kwargs: dict[str, object] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "bufsize": 0,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            process = subprocess.Popen(self._command, **popen_kwargs)
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
                        "version": "1.11.1",
                    },
                },
            }
        )
        try:
            result = self._read_rpc_result(request_id)
        except McpTransportError as error:
            raise McpTransportError(
                "TRANSPORT_UNAVAILABLE",
                network_request_sent=error.network_request_sent,
            ) from None

        if result.get("protocolVersion") != MCP_PROTOCOL_VERSION:
            raise McpTransportError(
                "TRANSPORT_UNAVAILABLE", network_request_sent=True
            )

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

        wrote = False
        try:
            process.stdin.write(encoded + b"\n")
            wrote = True
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            raise McpTransportError(
                "TRANSPORT_FAILED",
                network_request_sent=wrote,
            ) from None

    def _read_rpc_result(
        self, expected_id: int, *, network_request_sent: bool = True
    ) -> dict[str, Any]:
        try:
            raw_line = self._stdout_queue.get(timeout=self._timeout_seconds)
        except Empty:
            self._terminate_process()
            raise McpTransportError(
                "TRANSPORT_TIMEOUT",
                network_request_sent=network_request_sent,
            ) from None

        if raw_line is _OVERSIZED:
            self._terminate_process()
            raise McpTransportError(
                "RESPONSE_TOO_LARGE",
                network_request_sent=network_request_sent,
            )
        if raw_line is _QUEUE_FULL:
            self._terminate_process()
            raise McpTransportError(
                "RESPONSE_QUEUE_FULL",
                network_request_sent=network_request_sent,
            )
        if raw_line is _EOF or not isinstance(raw_line, bytes):
            raise McpTransportError(
                "TRANSPORT_FAILED",
                network_request_sent=network_request_sent,
            )

        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            ) from None

        if not isinstance(payload, dict):
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            )
        if payload.get("jsonrpc") != "2.0":
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            )
        if "method" in payload:
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            )
        response_id = payload.get("id")
        if type(response_id) is not type(expected_id) or response_id != expected_id:
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            )
        if "error" in payload:
            raise McpTransportError(
                "MCP_ERROR",
                network_request_sent=network_request_sent,
            )

        result = payload.get("result")
        if not isinstance(result, dict):
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            )
        return result

    @staticmethod
    def _decode_tool_result(
        result: dict[str, Any], *, network_request_sent: bool = True
    ) -> object:
        if result.get("isError") is True:
            error_code = "MCP_ERROR"
            content = result.get("content")
            if isinstance(content, list) and len(content) == 1:
                block = content[0]
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        # onshape-mcp 0.5.2 adds this prefix itself. Never
                        # infer HTTP status from the untrusted response body.
                        for status, code in (
                            (401, "AUTH_REQUIRED"),
                            (403, "SCOPE_DENIED"),
                            (404, "NOT_FOUND"),
                            (429, "RATE_LIMITED"),
                        ):
                            if text.startswith(f"API error (HTTP {status}): "):
                                error_code = code
                                break
            raise McpTransportError(
                error_code, network_request_sent=network_request_sent
            )

        if "structuredContent" in result:
            return result["structuredContent"]

        content = result.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            )
        block = content[0]
        if not isinstance(block, dict) or block.get("type") != "text":
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            )
        text = block.get("text")
        if not isinstance(text, str):
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise McpTransportError(
                "INVALID_RESPONSE",
                network_request_sent=network_request_sent,
            ) from None

    @staticmethod
    def _read_stdout(
        stream: BinaryIO,
        output: Queue[bytes | object],
        max_response_bytes: int,
    ) -> None:
        terminal = _EOF
        try:
            while True:
                line = stream.readline(max_response_bytes + 1)
                if not line:
                    break
                if len(line) > max_response_bytes:
                    terminal = _OVERSIZED
                    return
                try:
                    output.put_nowait(line)
                except Full:
                    terminal = _QUEUE_FULL
                    return
        except (OSError, ValueError):
            pass
        finally:
            if terminal is _EOF:
                try:
                    output.put_nowait(_EOF)
                except Full:
                    pass
            else:
                McpStdioSession._replace_queue_with(output, terminal)

    @staticmethod
    def _replace_queue_with(output: Queue[bytes | object], item: object) -> None:
        while True:
            try:
                output.get_nowait()
            except Empty:
                break
        try:
            output.put_nowait(item)
        except Full:
            pass

    @staticmethod
    def _drain_stderr(stream: BinaryIO) -> None:
        try:
            while stream.read(4096):
                pass
        except (OSError, ValueError):
            pass

    def _terminate_process(self) -> None:
        process = self._process
        if process is None:
            return

        if os.name == "nt" and process.poll() is None:
            try:
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass

        if process.poll() is not None:
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
