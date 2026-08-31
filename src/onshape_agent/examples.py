"""Named, repository-owned examples for offline workflow verification."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .demo import run_demo

EXAMPLE_NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")


class ExampleError(ValueError):
    """Raised when a named example cannot be loaded safely."""


def load_example(repo_root: Path, name: str) -> dict[str, Any]:
    """Load one approved example request from the repository."""

    if EXAMPLE_NAME_PATTERN.fullmatch(name) is None:
        raise ExampleError(f"Invalid example name: {name}")

    request_path = repo_root / "examples" / name / "request.json"
    if not request_path.is_file():
        raise ExampleError(f"Unknown example: {name}")

    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExampleError(f"Invalid example request: {name}") from error
    if not isinstance(request, dict) or request.get("name") != name:
        raise ExampleError(f"Invalid example request: {name}")
    if request.get("status") != "APPROVED":
        raise ExampleError(f"Example is not approved: {name}")
    return request


def run_named_example(
    name: str,
    output: Path,
    *,
    repo_root: Path,
) -> dict[str, object]:
    """Run a named example through the network-free pipeline."""

    request = load_example(repo_root, name)
    summary = run_demo(output, problem_brief=request, example_name=name)
    return {"example": name, **summary}
