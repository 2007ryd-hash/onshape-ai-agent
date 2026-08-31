from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _run_script(
    script: str,
    *arguments: str,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if POWERSHELL is None:
        pytest.skip("PowerShell is required for Windows installer tests")
    command = [
        POWERSHELL,
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(REPO_ROOT / "scripts" / script),
        *arguments,
    ]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        env=env,
    )


def test_install_all_hosts_and_runner_work_offline(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"

    result = _run_script(
        "install.ps1",
        "-HostTarget",
        "all",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["host_target"] == "all"
    assert summary["runtime_installed"] is False
    assert (codex_home / "skills" / "onshape-engineering" / "SKILL.md").is_file()
    assert (claude_home / "skills" / "onshape-engineering" / "SKILL.md").is_file()
    assert {
        path.name for path in (claude_home / "agents").glob("onshape-engineering-*.md")
    } == {
        "onshape-engineering-cad-agent.md",
        "onshape-engineering-drawing-agent.md",
        "onshape-engineering-engineering-agent.md",
        "onshape-engineering-visual-qa-agent.md",
    }

    state = json.loads((state_dir / "install.json").read_text(encoding="utf-8-sig"))
    assert Path(state["repo_root"]).resolve() == REPO_ROOT
    assert Path(state["python_path"]).is_file()

    runner = (
        codex_home
        / "skills"
        / "onshape-engineering"
        / "scripts"
        / "onshape-agent.ps1"
    )
    command = [
        POWERSHELL,
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(runner),
        "doctor",
        "--json",
        "--repo-root",
        str(REPO_ROOT),
    ]
    environment = dict(os.environ)
    environment["ONSHAPE_AGENT_STATE_DIR"] = str(state_dir)
    doctor = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )
    assert doctor.returncode == 0, doctor.stderr
    assert json.loads(doctor.stdout)["status"] == "READY_OFFLINE"


def test_install_refuses_unowned_destination_without_force(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    destination = codex_home / "skills" / "onshape-engineering"
    destination.mkdir(parents=True)
    (destination / "user-file.txt").write_text("keep", encoding="utf-8")

    result = _run_script(
        "install.ps1",
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(tmp_path / "state"),
    )

    assert result.returncode != 0
    assert "not owned" in result.stderr.lower()
    assert (destination / "user-file.txt").read_text(encoding="utf-8") == "keep"


def test_uninstall_removes_only_project_owned_installation(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"
    common = [
        "-HostTarget",
        "all",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
    ]
    install = _run_script("install.ps1", *common, "-SkipRuntimeInstall")
    assert install.returncode == 0, install.stderr
    unrelated = claude_home / "agents" / "keep-me.md"
    unrelated.write_text("user owned", encoding="utf-8")

    uninstall = _run_script("uninstall.ps1", *common)

    assert uninstall.returncode == 0, uninstall.stderr
    assert not (codex_home / "skills" / "onshape-engineering").exists()
    assert not (claude_home / "skills" / "onshape-engineering").exists()
    assert not list((claude_home / "agents").glob("onshape-engineering-*.md"))
    assert unrelated.read_text(encoding="utf-8") == "user owned"
    assert not (state_dir / "install.json").exists()
