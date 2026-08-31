from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from onshape_agent.cli import app
from onshape_agent.doctor import DoctorCheck, DoctorReport, inspect_installation

runner = CliRunner()


def _write_ready_fixture(root: Path) -> None:
    """Create the repository files that an offline install requires."""

    codex_manifest = root / "plugins" / "onshape-engineering-agent" / ".codex-plugin"
    claude_manifest = (
        root / "plugins" / "onshape-engineering-agent" / ".claude-plugin"
    )
    skill_root = (
        root
        / "plugins"
        / "onshape-engineering-agent"
        / "skills"
        / "onshape-engineering"
    )
    package_root = root / "src" / "onshape_agent"

    codex_manifest.mkdir(parents=True)
    claude_manifest.mkdir(parents=True)
    skill_root.mkdir(parents=True)
    package_root.mkdir(parents=True)
    (root / "examples" / "simple-bracket").mkdir(parents=True)
    (root / "runs").mkdir()

    manifest = {"name": "onshape-engineering-agent", "version": "0.2.0"}
    (codex_manifest / "plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (claude_manifest / "plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (skill_root / "SKILL.md").write_text(
        "---\nname: onshape-engineering\ndescription: Shared skill\n---\n",
        encoding="utf-8",
    )
    (root / "examples" / "simple-bracket" / "request.json").write_text(
        '{"name": "simple-bracket"}\n', encoding="utf-8"
    )
    (package_root / "__init__.py").write_text(
        '"""Fixture package."""\n', encoding="utf-8"
    )


def _check(report: DoctorReport, name: str) -> DoctorCheck:
    return next(check for check in report.checks if check.name == name)


def test_complete_fixture_is_ready_offline(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)

    report = inspect_installation(tmp_path)

    assert report.status == "READY_OFFLINE"
    assert report.provider_api_key_required is False
    assert report.onshape_transport == "not_configured"
    assert {
        check.name
        for check in report.checks
    } == {
        "python_version",
        "package_import",
        "codex_manifest",
        "claude_manifest",
        "shared_skill",
        "simple_bracket_request",
        "output_directory",
        "onshape_transport",
    }
    assert all(check.status == "PASS" for check in report.checks)


def test_real_repository_without_task_four_example_is_not_ready() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    report = inspect_installation(repo_root)

    assert report.status == "NOT_READY"
    assert _check(report, "simple_bracket_request").status == "FAIL"
    assert _check(report, "onshape_transport").status == "PASS"
    assert report.onshape_transport == "not_configured"


def test_package_import_is_scoped_to_repository_root(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    package_init = tmp_path / "src" / "onshape_agent" / "__init__.py"
    package_init.unlink()

    report = inspect_installation(tmp_path)

    assert report.status == "NOT_READY"
    assert _check(report, "package_import").status == "FAIL"


@pytest.mark.parametrize(
    ("relative_path", "check_name"),
    [
        (
            Path("plugins/onshape-engineering-agent/.codex-plugin/plugin.json"),
            "codex_manifest",
        ),
        (
            Path("plugins/onshape-engineering-agent/.claude-plugin/plugin.json"),
            "claude_manifest",
        ),
        (
            Path(
                "plugins/onshape-engineering-agent/skills/onshape-engineering/SKILL.md"
            ),
            "shared_skill",
        ),
        (Path("examples/simple-bracket/request.json"), "simple_bracket_request"),
    ],
)
def test_missing_installation_file_blocks_readiness(
    tmp_path: Path, relative_path: Path, check_name: str
) -> None:
    _write_ready_fixture(tmp_path)
    relative_path = tmp_path / relative_path
    relative_path.unlink()

    report = inspect_installation(tmp_path)

    assert report.status == "NOT_READY"
    assert _check(report, check_name).status == "FAIL"


def test_invalid_manifest_blocks_readiness(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    manifest_path = (
        tmp_path
        / "plugins"
        / "onshape-engineering-agent"
        / ".codex-plugin"
        / "plugin.json"
    )
    manifest_path.write_text("not json", encoding="utf-8")

    report = inspect_installation(tmp_path)

    assert report.status == "NOT_READY"
    assert _check(report, "codex_manifest").status == "FAIL"


def test_python_below_supported_version_blocks_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_ready_fixture(tmp_path)
    import onshape_agent.doctor as doctor_module

    monkeypatch.setattr(doctor_module.sys, "version_info", (3, 11, 9))

    report = doctor_module.inspect_installation(tmp_path)

    assert report.status == "NOT_READY"
    assert _check(report, "python_version").status == "FAIL"


def test_non_directory_output_root_blocks_readiness(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    output_file = tmp_path / "output-file"
    output_file.write_text("occupied", encoding="utf-8")

    report = inspect_installation(tmp_path, output_root=output_file)

    assert report.status == "NOT_READY"
    assert _check(report, "output_directory").status == "FAIL"


def test_doctor_json_command_returns_typed_report(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)

    result = runner.invoke(
        app, ["doctor", "--json", "--repo-root", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    report = DoctorReport.model_validate(json.loads(result.stdout))
    assert report.status == "READY_OFFLINE"
    assert report.onshape_transport == "not_configured"
    assert report.provider_api_key_required is False


def test_doctor_json_command_reports_not_ready_for_current_repository() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    result = runner.invoke(app, ["doctor", "--json", "--repo-root", str(repo_root)])

    assert result.exit_code == 1
    report = DoctorReport.model_validate(json.loads(result.stdout))
    assert report.status == "NOT_READY"


def test_doctor_does_not_echo_provider_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_ready_fixture(tmp_path)
    secret = "provider-secret-that-must-not-appear"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

    result = runner.invoke(
        app, ["doctor", "--json", "--repo-root", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert secret not in result.stdout


def test_doctor_models_are_strict() -> None:
    with pytest.raises(ValidationError):
        DoctorCheck(name="python_version", status="pass", detail="ok")
    with pytest.raises(ValidationError):
        DoctorCheck(
            name="python_version",
            status="PASS",
            detail="ok",
            unexpected="not allowed",
        )
    with pytest.raises(ValidationError):
        DoctorReport(status="READY_OFFLINE", provider_api_key_required=True)
