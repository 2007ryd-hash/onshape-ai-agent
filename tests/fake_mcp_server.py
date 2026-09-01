"""Deterministic JSON-RPC child used by the MCP stdio tests.

The script deliberately behaves like a small MCP server over newline-delimited
UTF-8 JSON.  It has no access to credentials or the network.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
SECRET = "fake-child-secret-must-not-leak"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="normal")
    parser.add_argument("--trace", type=Path)
    return parser.parse_args()


def _record(path: Path | None, message: dict[str, Any]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        json.dump(message, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")


def _send(message: object) -> None:
    encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def _send_bytes(message: bytes) -> None:
    sys.stdout.buffer.write(message + b"\n")
    sys.stdout.buffer.flush()


def _tool_response(request_id: object, scenario: str, tool_name: str) -> object:
    if scenario == "rpc-error" or tool_name == "rpc_error":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32001, "message": SECRET},
        }

    if scenario == "wrong-id" or tool_name == "wrong_id":
        return {
            "jsonrpc": "2.0",
            "id": int(request_id) + 100,
            "result": {"content": [{"type": "text", "text": "{}"}]},
        }

    if scenario == "server-request" or tool_name == "server_request":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "sampling/createMessage",
            "params": {"detail": SECRET},
            "result": {"content": [{"type": "text", "text": "{}"}]},
        }

    if scenario == "oversized" or tool_name == "oversized":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": SECRET + ("x" * 4096)}]
            },
        }

    if scenario == "malformed" or tool_name == "malformed":
        return None

    if scenario == "structured" or tool_name == "structured":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "structuredContent": {"source": "structured", "value": 7},
                "content": [{"type": "text", "text": '{"source":"text"}'}],
            },
        }

    if scenario == "multi-content" or tool_name == "multi_content":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {"type": "text", "text": '{"part":1}'},
                    {"type": "text", "text": '{"part":2}'},
                ]
            },
        }

    if scenario == "non-text" or tool_name == "non_text":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "image", "data": "not-used"}]},
        }

    if scenario == "stderr-flood" or tool_name == "stderr_flood":
        sys.stderr.buffer.write((SECRET + "\n").encode("utf-8"))
        sys.stderr.buffer.write(b"s" * (1024 * 1024))
        sys.stderr.buffer.write(b"\n")
        sys.stderr.buffer.flush()

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"content": [{"type": "text", "text": '{"configured":true}'}]},
    }


def main() -> int:
    args = _parse_args()
    initialized = False

    for raw_line in sys.stdin.buffer:
        try:
            message = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(message, dict):
            continue
        _record(args.trace, message)

        method = message.get("method")
        if method == "initialize":
            if args.scenario == "init-error":
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {"code": -32000, "message": SECRET},
                    }
                )
            elif args.scenario == "init-malformed":
                _send_bytes(b"not-json")
            else:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "result": {
                            "protocolVersion": PROTOCOL_VERSION,
                            "capabilities": {},
                            "serverInfo": {"name": "fake", "version": "1"},
                        },
                    }
                )
        elif method == "notifications/initialized":
            initialized = True
        elif method == "tools/call":
            if not initialized:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {"code": -32002, "message": "not initialized"},
                    }
                )
                continue

            request_id = message.get("id")
            tool_name = message.get("params", {}).get("name")
            if args.scenario == "hang" or tool_name == "hang":
                time.sleep(60)
                continue
            if args.scenario == "exit" or tool_name == "exit":
                return 0
            if args.scenario == "malformed" or tool_name == "malformed":
                _send_bytes(b"not-json")
                continue

            response = _tool_response(request_id, args.scenario, tool_name)
            if response is not None:
                _send(response)
        elif method == "notifications/ping":
            continue

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
