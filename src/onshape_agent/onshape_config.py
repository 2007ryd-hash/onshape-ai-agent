"""Safe, formatting-preserving updates for the upstream Onshape MCP config."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from tomlkit import document, dumps, parse, table
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import Table

CALLBACK_URI = "http://localhost:18338/callback"


class OnshapeConfigError(ValueError):
    """Raised when the upstream configuration cannot be safely updated."""


def _read_document(config_path: Path) -> Any:
    if not config_path.is_file():
        return document()
    content = config_path.read_text(encoding="utf-8-sig")
    if not content.strip():
        return document()
    try:
        return parse(content)
    except TOMLKitError as error:
        raise OnshapeConfigError("existing Onshape config is not valid TOML") from error


def _update_auth(
    config: Any,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> None:
    auth = config.get("auth")
    if auth is None:
        auth = table()
        config["auth"] = auth
    if not isinstance(auth, Table):
        raise OnshapeConfigError("existing auth section is not a TOML table")
    auth["client_id"] = client_id
    auth["client_secret"] = client_secret
    auth["redirect_uri"] = redirect_uri


def _atomic_write(config_path: Path, content: str) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary_path = config_path.with_name(f".{config_path.name}.{token}.tmp")
    backup_path = config_path.with_name(f".{config_path.name}.{token}.bak")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, config_path)
    finally:
        for path in (temporary_path, backup_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def update_config(
    config_path: Path | str,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str = CALLBACK_URI,
) -> None:
    """Parse, update, and atomically replace an upstream TOML config file."""

    path = Path(config_path)
    config = _read_document(path)
    _update_auth(
        config,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    rendered = dumps(config)
    _atomic_write(path, rendered)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Read credentials from JSON stdin and update one config path silently."""

    arguments = _parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise OnshapeConfigError("credential payload must be an object")
        client_id = payload.get("client_id")
        client_secret = payload.get("client_secret")
        redirect_uri = payload.get("redirect_uri", CALLBACK_URI)
        fields = (client_id, client_secret, redirect_uri)
        if not all(isinstance(value, str) for value in fields):
            raise OnshapeConfigError("credential payload fields must be strings")
        update_config(
            arguments.config_path,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    except (OSError, OnshapeConfigError, TOMLKitError, json.JSONDecodeError):
        # Never print parser details: they can include credential-bearing input.
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by PowerShell tests
    raise SystemExit(main())
