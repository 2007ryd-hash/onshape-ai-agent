from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from onshape_agent.cli import app

runner = CliRunner()


def test_simple_bracket_example_writes_complete_offline_result(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    result = runner.invoke(
        app,
        [
            "example",
            "simple-bracket",
            "--output",
            str(tmp_path),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["example"] == "simple-bracket"
    assert summary["network_request_sent"] is False
    assert summary["visual_mode"] == "simulated"

    run_dir = Path(summary["run_dir"])
    artifact_names = {path.name for path in (run_dir / "artifacts").glob("*.json")}
    assert artifact_names == {
        "problem_brief_v1.json",
        "task_graph_v1.json",
        "execution_plan_v1.json",
        "execution_report_v1.json",
        "drawing_plan_v1.json",
        "visual_report_v1.json",
        "diagnosis_v1.json",
    }

    problem_brief = json.loads(
        (run_dir / "artifacts" / "problem_brief_v1.json").read_text(
            encoding="utf-8"
        )
    )["payload"]
    assert problem_brief["part"] == "simple_bracket"
    assert problem_brief["dimensions_mm"] == {
        "height": 40,
        "hole_diameter": 4,
        "hole_edge_offset": 6,
        "thickness": 8,
        "width": 60,
    }

    drawing = json.loads(
        (run_dir / "artifacts" / "drawing_plan_v1.json").read_text(
            encoding="utf-8"
        )
    )["payload"]
    assert {view["orientation"] for view in drawing["views"]} == {
        "front",
        "top",
        "right",
        "isometric",
    }


def test_example_rejects_unknown_or_unsafe_names(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    unknown = runner.invoke(
        app,
        [
            "example",
            "missing-example",
            "--output",
            str(tmp_path),
            "--repo-root",
            str(repo_root),
        ],
    )
    unsafe = runner.invoke(
        app,
        [
            "example",
            "../simple-bracket",
            "--output",
            str(tmp_path),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert unknown.exit_code == 2
    assert "Unknown example" in unknown.output
    assert unsafe.exit_code == 2
    assert "Invalid example name" in unsafe.output
