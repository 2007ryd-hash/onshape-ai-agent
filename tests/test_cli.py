from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from onshape_agent.cli import app

runner = CliRunner()


def test_demo_writes_auditable_artifacts_without_network(tmp_path) -> None:
    result = runner.invoke(app, ["demo", "--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    run_dir = Path(summary["run_dir"])
    assert summary["status"] == "REPAIR_ROUTED"
    assert summary["network_request_sent"] is False
    assert summary["repair_target"] == "cad_agent"
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "artifacts" / "task_graph_v1.json").exists()
    assert (run_dir / "artifacts" / "execution_plan_v1.json").exists()
    assert (run_dir / "artifacts" / "visual_report_v1.json").exists()

    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events] == [
        "RUN_STARTED",
        "TASK_GRAPH_SELECTED",
        "CAD_PLAN_EXECUTED",
        "VISUAL_ISSUE_REPORTED",
        "REPAIR_ROUTED",
    ]


def test_auth_status_json_reports_only_local_presence(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "onshape-mcp"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'client_secret = "private-config"', encoding="utf-8"
    )
    (config_dir / "tokens.json").write_text(
        '{"access_token":"private-token"}', encoding="utf-8"
    )
    monkeypatch.setenv("ONSHAPE_MCP_CONFIG_DIR", str(config_dir))

    result = runner.invoke(app, ["auth", "status", "--json"])

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["config_present"] is True
    assert summary["tokens_present"] is True
    assert summary["network_request_sent"] is False
    assert "private-config" not in result.stdout
    assert "private-token" not in result.stdout


def test_live_list_documents_outputs_a_safe_receipt(monkeypatch) -> None:
    from onshape_agent.live_service import LiveService

    session = _FakeSession(
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
    monkeypatch.setattr(
        "onshape_agent.cli.LiveService",
        lambda: LiveService(session_factory=lambda: session),
    )

    result = runner.invoke(app, ["live", "list-documents", "--limit", "1", "--json"])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.stdout)
    assert receipt["operation"] == "list_documents"
    assert receipt["status"] == "SUCCEEDED"
    assert receipt["evidence_summary"] == {"item_count": 1}
    assert "private@example.com" not in result.stdout
    assert "private-body" not in result.stdout
    assert session.calls == [
        (
            "onshape_api_call",
            {"endpoint": "getDocuments", "query_params": {"limit": "1"}},
        )
    ]


def test_live_read_document_outputs_a_safe_receipt(monkeypatch) -> None:
    from onshape_agent.live_service import LiveService

    session = _FakeSession(
        {
            "onshape_api_call": {
                "id": "doc-123",
                "owner": {"email": "private@example.com"},
                "description": "private-body",
            }
        }
    )
    monkeypatch.setattr(
        "onshape_agent.cli.LiveService",
        lambda: LiveService(session_factory=lambda: session),
    )

    result = runner.invoke(
        app,
        ["live", "read-document", "--document-id", "doc-123", "--json"],
    )

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.stdout)
    assert receipt["operation"] == "get_document"
    assert receipt["evidence_summary"] == {"document_id_matches": True}
    assert "private@example.com" not in result.stdout
    assert "private-body" not in result.stdout


def test_live_list_documents_rejects_limits_outside_one_to_one_hundred() -> None:
    result = runner.invoke(app, ["live", "list-documents", "--limit", "101"])

    assert result.exit_code == 2
    assert "limit" in result.output.lower()


class _FakeSession:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append((name, arguments))
        return self.responses[name]
