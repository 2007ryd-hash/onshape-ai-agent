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
