from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _run_script(
    script: str,
    *arguments: str,
    check: bool = False,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    cwd: Path | None = None,
    repo_root: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    if POWERSHELL is None:
        pytest.skip("PowerShell is required for Windows installer tests")
    command = [
        POWERSHELL,
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-InputFormat",
        "Text",
        "-File",
        str(repo_root / "scripts" / script),
        *arguments,
    ]
    return subprocess.run(
        command,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        env=env,
        input=input_text,
    )


def _fake_tools(
    tmp_path: Path,
    *,
    node_version: str = "v24.0.0",
    npx_version: str = "0.5.2",
    include_node: bool = True,
    npx_exit_code: int = 0,
) -> tuple[Path, Path]:
    """Create harmless node/npx shims and return their bin and trace paths."""

    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    trace_path = tmp_path / "npx-args.txt"
    if include_node:
        (bin_dir / "node.cmd").write_text(
            f'@echo off\r\nif "%~1"=="--version" echo {node_version}\r\nexit /b 0\r\n',
            encoding="ascii",
        )
    (bin_dir / "npx.cmd").write_text(
        "@echo off\r\n"
        '>"%FAKE_NPX_TRACE%" echo %*\r\n'
        f'if "%~3"=="--version" echo onshape-mcp {npx_version}\r\n'
        f"exit /b {npx_exit_code}\r\n",
        encoding="ascii",
    )
    return bin_dir, trace_path


def _isolated_environment(tmp_path: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "CODEX_HOME": str(tmp_path / "isolated-codex"),
            "CLAUDE_CONFIG_DIR": str(tmp_path / "isolated-claude"),
            "APPDATA": str(tmp_path / "isolated-appdata"),
            "LOCALAPPDATA": str(tmp_path / "isolated-localappdata"),
            "ONSHAPE_AGENT_STATE_DIR": str(tmp_path / "isolated-state"),
        }
    )
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "ONSHAPE_MCP_CONFIG_DIR"):
        environment.pop(name, None)
    return environment


def _with_fake_npx(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir, trace_path = _fake_tools(tmp_path)
    environment = _isolated_environment(tmp_path)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    environment["FAKE_NPX_TRACE"] = str(trace_path)
    return environment, trace_path


def _with_fake_tools(
    tmp_path: Path,
    *,
    node_version: str = "v24.0.0",
    npx_version: str = "0.5.2",
    include_node: bool = True,
    npx_exit_code: int = 0,
    only_fake_path: bool = False,
) -> tuple[dict[str, str], Path, Path]:
    bin_dir, trace_path = _fake_tools(
        tmp_path,
        node_version=node_version,
        npx_version=npx_version,
        include_node=include_node,
        npx_exit_code=npx_exit_code,
    )
    environment = _isolated_environment(tmp_path)
    environment["PATH"] = (
        str(bin_dir)
        if only_fake_path
        else f"{bin_dir}{os.pathsep}{environment['PATH']}"
    )
    environment["FAKE_NPX_TRACE"] = str(trace_path)
    return environment, trace_path, bin_dir


def _install_for_setup(tmp_path: Path, environment: dict[str, str]) -> Path:
    state_dir = tmp_path / "setup-state"
    result = _run_script(
        "install.ps1",
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(tmp_path / "setup-codex"),
        "-StateDir",
        str(state_dir),
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    environment["ONSHAPE_AGENT_STATE_DIR"] = str(state_dir)
    return state_dir


def test_install_all_hosts_and_runner_work_offline(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"

    environment, _ = _with_fake_npx(tmp_path)
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
        env=environment,
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
        codex_home / "skills" / "onshape-engineering" / "scripts" / "onshape-agent.ps1"
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

    environment, _ = _with_fake_npx(tmp_path)
    result = _run_script(
        "install.ps1",
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(tmp_path / "state"),
        env=environment,
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
    environment, _ = _with_fake_npx(tmp_path)
    install = _run_script(
        "install.ps1", *common, "-SkipRuntimeInstall", env=environment
    )
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


def test_setup_scripts_pin_safe_onshape_command_and_callback() -> None:
    configure = (REPO_ROOT / "scripts" / "configure-onshape.ps1").read_text(
        encoding="utf-8"
    )
    login = (REPO_ROOT / "scripts" / "login-onshape.ps1").read_text(encoding="utf-8")
    launcher = (REPO_ROOT / "scripts" / "onshape-agent.ps1").read_text(encoding="utf-8")

    assert "npx.cmd" in configure
    assert "npx.cmd" in login
    assert "onshape-mcp@0.5.2" in configure
    assert "onshape-mcp@0.5.2" in login
    assert "http://localhost:18338/callback" in configure
    assert "-AsSecureString" in configure
    assert (
        "clientsecret" not in configure.lower().split("param", 1)[-1].split(")", 1)[0]
    )
    assert "Write-JsonAtomic" not in configure
    assert "PYTHONPATH" in launcher
    assert "onshape_agent.onshape_config" in configure
    assert "--config-path" in configure


def test_configure_writes_only_upstream_config_without_echoing_secret(
    tmp_path: Path,
) -> None:
    environment, _ = _with_fake_npx(tmp_path)
    appdata = tmp_path / "appdata"
    localappdata = tmp_path / "localappdata"
    environment["APPDATA"] = str(appdata)
    environment["LOCALAPPDATA"] = str(localappdata)
    state_dir = _install_for_setup(tmp_path, environment)
    state_before = (state_dir / "install.json").read_bytes()
    secret = "secret-value-that-must-not-leak"

    result = _run_script(
        "configure-onshape.ps1",
        env=environment,
        input_text=f"client-id-value\n{secret}\n",
    )

    assert result.returncode == 0, result.stderr
    config_path = appdata / "onshape-mcp" / "config.toml"
    assert config_path.is_file()
    config = config_path.read_text(encoding="utf-8-sig")
    assert 'client_id = "client-id-value"' in config
    assert f'client_secret = "{secret}"' in config
    assert 'redirect_uri = "http://localhost:18338/callback"' in config
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert (state_dir / "install.json").read_bytes() == state_before


def test_login_invokes_only_explicit_pinned_auth_login(tmp_path: Path) -> None:
    environment, trace_path = _with_fake_npx(tmp_path)
    environment["APPDATA"] = str(tmp_path / "appdata")
    environment["LOCALAPPDATA"] = str(tmp_path / "localappdata")

    result = _run_script("login-onshape.ps1", env=environment)

    assert result.returncode == 0, result.stderr
    assert trace_path.read_text(encoding="utf-8").strip() == (
        "--yes onshape-mcp@0.5.2 auth login"
    )
    assert "auth login" in result.stdout


def test_install_state_records_non_secret_mcp_metadata(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    environment, trace_path = _with_fake_npx(tmp_path)
    environment["APPDATA"] = str(tmp_path / "appdata")
    environment["LOCALAPPDATA"] = str(tmp_path / "localappdata")

    result = _run_script(
        "install.ps1",
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    state = json.loads((state_dir / "install.json").read_text(encoding="utf-8-sig"))
    assert state["mcp_command"] == ["npx.cmd", "--yes", "onshape-mcp@0.5.2"]
    assert state["mcp_version"] == "0.5.2"
    assert state["mcp_present"] is True
    serialized = json.dumps(state).lower()
    assert "client_secret" not in serialized
    assert "secret-value" not in serialized
    assert trace_path.read_text(encoding="utf-8").strip() == (
        "--yes onshape-mcp@0.5.2 --version"
    )


def test_root_launcher_works_from_arbitrary_cwd_with_source_import(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "install.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "repo_root": str(REPO_ROOT),
                "python_path": sys.executable,
            }
        ),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["ONSHAPE_AGENT_STATE_DIR"] = str(state_dir)

    result = _run_script(
        "onshape-agent.ps1",
        "doctor",
        "--json",
        env=environment,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "READY_OFFLINE"


def test_uninstall_preserves_upstream_config_and_tokens(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    appdata = tmp_path / "appdata"
    localappdata = tmp_path / "localappdata"
    config_dir = appdata / "onshape-mcp"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.toml"
    config_path.write_text('[auth]\nclient_secret = "private"\n', encoding="utf-8")
    token_dir = localappdata / "onshape-mcp"
    token_dir.mkdir(parents=True)
    token_path = token_dir / "tokens.json"
    token_path.write_text('{"access_token":"private"}\n', encoding="utf-8")
    environment, _ = _with_fake_npx(tmp_path)
    environment["APPDATA"] = str(appdata)
    environment["LOCALAPPDATA"] = str(localappdata)
    common = [
        "-HostTarget",
        "codex",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
    ]

    install = _run_script(
        "install.ps1", *common, "-SkipRuntimeInstall", env=environment
    )
    assert install.returncode == 0, install.stderr
    uninstall = _run_script("uninstall.ps1", *common, env=environment)

    assert uninstall.returncode == 0, uninstall.stderr
    assert config_path.is_file()
    assert token_path.is_file()
    assert "preserve" in uninstall.stdout.lower()


def test_uninstall_ignores_tampered_agent_paths(tmp_path: Path) -> None:
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    install = _run_script(
        "install.ps1",
        "-HostTarget",
        "claude",
        "-SkipRuntimeInstall",
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )
    assert install.returncode == 0, install.stderr

    external_file = tmp_path / "must-not-be-removed.md"
    external_file.write_text("user content", encoding="utf-8")
    marker_path = claude_home / "agents" / ".onshape-engineering-agent-owner.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["installed_files"] = [str(external_file)]
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    uninstall = _run_script(
        "uninstall.ps1",
        "-HostTarget",
        "claude",
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )

    assert uninstall.returncode == 0, uninstall.stderr
    assert external_file.read_text(encoding="utf-8") == "user content"
    assert not marker_path.exists()
    assert not list((claude_home / "agents").glob("onshape-engineering-*.md"))


def test_uninstall_preflights_all_owned_targets_before_staging(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    arguments = [
        "-HostTarget",
        "all",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
    ]
    install = _run_script("install.ps1", *arguments, env=environment)
    assert install.returncode == 0, install.stderr

    agent_marker = claude_home / "agents" / ".onshape-engineering-agent-owner.json"
    marker = json.loads(agent_marker.read_text(encoding="utf-8"))
    marker["repo_root"] = str(tmp_path / "other-repo")
    agent_marker.write_text(json.dumps(marker), encoding="utf-8")

    uninstall = _run_script(
        "uninstall.ps1",
        "-HostTarget",
        "all",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )

    assert uninstall.returncode != 0
    assert "owned" in uninstall.stderr.lower()
    assert (codex_home / "skills" / "onshape-engineering").exists()
    assert (claude_home / "skills" / "onshape-engineering").exists()
    assert agent_marker.exists()
    assert (state_dir / "install.json").exists()


@pytest.mark.parametrize("failure_stage", ["2", "state"])
def test_uninstall_restores_all_staged_targets_after_failure(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    arguments = [
        "-HostTarget",
        "all",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
    ]
    install = _run_script("install.ps1", *arguments, env=environment)
    assert install.returncode == 0, install.stderr
    state_path = state_dir / "install.json"
    codex_marker = (
        codex_home / "skills" / "onshape-engineering.onshape-agent-owner.json"
    )
    claude_marker = (
        claude_home / "skills" / "onshape-engineering.onshape-agent-owner.json"
    )
    agent_marker = claude_home / "agents" / ".onshape-engineering-agent-owner.json"
    preserved_files = [state_path, codex_marker, claude_marker, agent_marker]
    preserved_files.extend(
        sorted((claude_home / "agents").glob("onshape-engineering-*.md"))
    )
    before = {path: path.read_bytes() for path in preserved_files}

    environment["ONSHAPE_AGENT_TEST_UNINSTALL_STAGE"] = failure_stage
    uninstall = _run_script(
        "uninstall.ps1",
        "-HostTarget",
        "all",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )

    assert uninstall.returncode != 0
    assert "uninstall" in uninstall.stderr.lower()
    for path, content in before.items():
        assert path.read_bytes() == content
    assert (codex_home / "skills" / "onshape-engineering").exists()
    assert (claude_home / "skills" / "onshape-engineering").exists()
    assert not list(state_dir.glob(".onshape-agent-uninstall-*"))


def test_uninstall_retains_backup_when_rollback_fails(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    arguments = [
        "-HostTarget",
        "codex",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
    ]
    installed = _run_script(
        "install.ps1", *arguments, "-SkipRuntimeInstall", env=environment
    )
    assert installed.returncode == 0, installed.stderr
    environment["ONSHAPE_AGENT_TEST_UNINSTALL_STAGE"] = "state"
    environment["ONSHAPE_AGENT_TEST_UNINSTALL_ROLLBACK"] = "1"

    result = _run_script("uninstall.ps1", *arguments, env=environment)

    assert result.returncode != 0
    assert "rollback failed" in result.stderr.lower()
    backups = list(state_dir.glob(".onshape-agent-uninstall-*/item-0001"))
    assert len(backups) == 1
    assert (backups[0] / "SKILL.md").is_file()
    assert (state_dir / "install.json").is_file()
    assert Path(
        f"{codex_home / 'skills' / 'onshape-engineering'}.onshape-agent-owner.json"
    ).is_file()


def test_uninstall_reports_cleanup_warning_after_successful_staging(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    arguments = [
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
    ]
    install = _run_script("install.ps1", *arguments, env=environment)
    assert install.returncode == 0, install.stderr

    environment["ONSHAPE_AGENT_TEST_UNINSTALL_CLEANUP"] = "1"
    uninstall = _run_script(
        "uninstall.ps1",
        "-HostTarget",
        "codex",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )

    assert uninstall.returncode == 0, uninstall.stderr
    summary = json.loads(uninstall.stdout)
    assert summary["cleanup_warnings"]
    assert not (codex_home / "skills" / "onshape-engineering").exists()
    assert not (state_dir / "install.json").exists()
    assert list(state_dir.glob(".onshape-agent-uninstall-*"))


def test_install_rejects_state_owned_by_another_repo_without_force(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_path = state_dir / "install.json"
    original = json.dumps({"repo_root": str(tmp_path / "other-repo")})
    state_path.write_text(original, encoding="utf-8")
    environment, _, _ = _with_fake_tools(tmp_path)
    arguments = [
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
    ]

    rejected = _run_script("install.ps1", *arguments, env=environment)

    assert rejected.returncode != 0
    assert "state" in rejected.stderr.lower()
    assert "owned" in rejected.stderr.lower()
    assert state_path.read_text(encoding="utf-8") == original
    assert not (codex_home / "skills" / "onshape-engineering").exists()

    forced = _run_script("install.ps1", *arguments, "-Force", env=environment)

    assert forced.returncode == 0, forced.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert Path(state["repo_root"]).resolve() == REPO_ROOT


def test_install_commit_cleanup_warning_keeps_new_install_consistent(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    arguments = [
        "-HostTarget",
        "all",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
    ]
    first = _run_script("install.ps1", *arguments, env=environment)
    assert first.returncode == 0, first.stderr

    environment["ONSHAPE_AGENT_TEST_FAIL_COMMIT_CLEANUP"] = "1"
    second = _run_script("install.ps1", *arguments, env=environment)

    assert second.returncode == 0, second.stderr
    summary = json.loads(second.stdout)
    assert summary["cleanup_warnings"]
    assert (codex_home / "skills" / "onshape-engineering").exists()
    assert (claude_home / "skills" / "onshape-engineering").exists()
    assert (state_dir / "install.json").exists()
    assert list(tmp_path.glob("**/*.onshape-agent-backup-*"))


def test_install_validates_pinned_mcp_before_creating_host_links(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(
        tmp_path,
        npx_version="0.5.1",
    )

    result = _run_script(
        "install.ps1",
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )

    assert result.returncode != 0
    assert "pinned onshape-mcp@0.5.2" in result.stderr
    assert not (codex_home / "skills" / "onshape-engineering").exists()
    assert not (state_dir / "install.json").exists()


def test_install_rolls_back_first_host_when_second_host_fails(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    environment["ONSHAPE_AGENT_TEST_FAIL_HOST"] = "claude"

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
        env=environment,
    )

    assert result.returncode != 0
    assert "injected" in result.stderr.lower()
    assert not (codex_home / "skills" / "onshape-engineering").exists()
    assert not (claude_home / "skills" / "onshape-engineering").exists()
    assert not (state_dir / "install.json").exists()
    assert not list(tmp_path.glob("**/*.onshape-agent-owner.json"))


def test_install_restores_state_and_hosts_after_state_write_failure(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    arguments = [
        "-HostTarget",
        "all",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
    ]

    first = _run_script("install.ps1", *arguments, env=environment)
    assert first.returncode == 0, first.stderr
    state_path = state_dir / "install.json"
    codex_marker = (
        codex_home / "skills" / "onshape-engineering.onshape-agent-owner.json"
    )
    claude_marker = (
        claude_home / "skills" / "onshape-engineering.onshape-agent-owner.json"
    )
    agent_marker = claude_home / "agents" / ".onshape-engineering-agent-owner.json"
    preserved_files = [state_path, codex_marker, claude_marker, agent_marker]
    preserved_files.extend(
        sorted((claude_home / "agents").glob("onshape-engineering-*.md"))
    )
    before = {path: path.read_bytes() for path in preserved_files}

    environment["ONSHAPE_AGENT_TEST_FAIL_AFTER_STATE_WRITE"] = "1"
    second = _run_script("install.ps1", *arguments, env=environment)

    assert second.returncode != 0
    assert "injected" in second.stderr.lower()
    for path, content in before.items():
        assert path.read_bytes() == content
    assert (codex_home / "skills" / "onshape-engineering").is_dir()
    assert (claude_home / "skills" / "onshape-engineering").is_dir()
    assert not list(tmp_path.glob("**/*.onshape-agent-backup-*"))
    assert not list(tmp_path.glob("**/*.tmp"))
    assert not list(tmp_path.glob("**/*.bak"))


def test_install_reports_original_and_rollback_errors(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)
    environment["ONSHAPE_AGENT_TEST_FAIL_AFTER_STATE_WRITE"] = "1"
    environment["ONSHAPE_AGENT_TEST_FAIL_ROLLBACK"] = "1"

    result = _run_script(
        "install.ps1",
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )

    assert result.returncode != 0
    message = result.stderr.lower()
    assert "installation failed" in message
    assert "rollback failed" in message
    assert "after state write" in message
    assert "rollback" in message


@pytest.mark.parametrize(
    "marker_kind", ["codex-skill", "claude-skill", "claude-agents"]
)
def test_install_rejects_unowned_marker_without_destination(
    tmp_path: Path,
    marker_kind: str,
) -> None:
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    state_dir = tmp_path / "state"
    if marker_kind == "codex-skill":
        destination = codex_home / "skills" / "onshape-engineering"
        host_target = "codex"
        marker = Path(f"{destination}.onshape-agent-owner.json")
    elif marker_kind == "claude-skill":
        destination = claude_home / "skills" / "onshape-engineering"
        host_target = "claude"
        marker = Path(f"{destination}.onshape-agent-owner.json")
    else:
        destination = claude_home / "agents"
        host_target = "claude"
        marker = destination / ".onshape-engineering-agent-owner.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps({"repo_root": str(tmp_path / "other-repo")}), encoding="utf-8"
    )

    environment, _, _ = _with_fake_tools(tmp_path)
    result = _run_script(
        "install.ps1",
        "-HostTarget",
        host_target,
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
        env=environment,
    )

    assert result.returncode != 0
    assert "marker" in result.stderr.lower()
    assert marker.read_text(encoding="utf-8") == json.dumps(
        {"repo_root": str(tmp_path / "other-repo")}
    )
    if marker_kind != "claude-agents":
        assert not destination.exists()
    else:
        assert not list(destination.glob("onshape-engineering-*.md"))


def test_skip_runtime_install_rejects_python_missing_runtime_dependencies(
    tmp_path: Path,
) -> None:
    mini_repo = tmp_path / "repo-without-runtime-dependencies"
    shutil.copytree(
        REPO_ROOT,
        mini_repo,
        ignore=shutil.ignore_patterns(
            ".venv",
            ".git",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
        ),
    )
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(mini_repo / ".venv")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (mini_repo / ".venv" / "Scripts" / "python.exe").is_file()
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    environment, _, _ = _with_fake_tools(tmp_path)

    result = _run_script(
        "install.ps1",
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
        env=environment,
        cwd=tmp_path,
        repo_root=mini_repo,
    )

    assert result.returncode != 0
    assert "import onshape_agent and runtime dependencies" in result.stderr.lower()
    assert not (codex_home / "skills" / "onshape-engineering").exists()
    assert not (state_dir / "install.json").exists()


def test_install_script_uses_one_atomic_json_writer_for_state_and_markers() -> None:
    install = (REPO_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    assert install.count("function Write-JsonAtomic") == 1
    assert "Write-JsonAtomic $marker" in install
    assert "Write-JsonAtomic $statePath" in install


@pytest.mark.parametrize("removed_host", ["codex", "claude"])
@pytest.mark.parametrize("remove_runtime", [False, True])
def test_partial_uninstall_preserves_remaining_host_state_and_runtime(
    tmp_path: Path, removed_host: str, remove_runtime: bool
) -> None:
    # Keep every deletion target in a miniature repository, including .venv.
    mini_repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", mini_repo / "scripts")
    runtime = mini_repo / ".venv"
    runtime.mkdir()
    sentinel = runtime / "keep-runtime.txt"
    sentinel.write_text("runtime", encoding="utf-8")
    codex_home, claude_home = tmp_path / "codex", tmp_path / "claude"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    paths = []
    for home in (codex_home, claude_home):
        destination = home / "skills" / "onshape-engineering"
        destination.mkdir(parents=True)
        Path(f"{destination}.onshape-agent-owner.json").write_text(
            json.dumps({"repo_root": str(mini_repo)}), encoding="utf-8"
        )
        paths.append(destination)
    state_path = state_dir / "install.json"
    state_path.write_text(
        json.dumps(
            {
                "repo_root": str(mini_repo),
                "python_path": sys.executable,
                "host_target": "all",
                "installed_paths": [str(path) for path in paths],
            }
        ),
        encoding="utf-8",
    )
    state_before = state_path.read_bytes()
    args = [
        "-HostTarget",
        removed_host,
        "-CodexHome",
        str(codex_home if removed_host == "codex" else tmp_path / "unused-codex"),
        "-ClaudeConfigDir",
        str(claude_home if removed_host == "claude" else tmp_path / "unused-claude"),
        "-StateDir",
        str(state_dir),
    ]
    if remove_runtime:
        args.append("-RemoveRuntime")
    result = _run_script("uninstall.ps1", *args, repo_root=mini_repo)
    assert result.returncode == 0, result.stderr
    removed_index = 0 if removed_host == "codex" else 1
    assert not paths[removed_index].exists()
    assert paths[1 - removed_index].is_dir()
    assert state_path.is_file(), "remaining host still requires shared install.json"
    assert state_path.read_bytes() == state_before
    assert sentinel.read_text(encoding="utf-8") == "runtime"
    assert json.loads(result.stdout)["shared_runtime_required"] is True

    # The final host removal must still be able to clean up shared resources.
    final = _run_script(
        "uninstall.ps1",
        "-HostTarget",
        "claude" if removed_host == "codex" else "codex",
        "-CodexHome",
        str(codex_home),
        "-ClaudeConfigDir",
        str(claude_home),
        "-StateDir",
        str(state_dir),
        "-RemoveRuntime",
        repo_root=mini_repo,
    )
    assert final.returncode == 0, final.stderr
    assert not state_path.exists()
    assert not runtime.exists()


@pytest.mark.parametrize("absolute_override", [True, False])
def test_configure_and_install_presence_follow_xdg_paths(
    tmp_path: Path, absolute_override: bool
) -> None:
    environment, _, _ = _with_fake_tools(tmp_path)
    appdata, localappdata = tmp_path / "appdata", tmp_path / "localappdata"
    xdg_config, xdg_data = tmp_path / "xdg-config", tmp_path / "xdg-data"
    environment.update(
        {
            "APPDATA": str(appdata),
            "LOCALAPPDATA": str(localappdata),
            "XDG_CONFIG_HOME": str(xdg_config)
            if absolute_override
            else "relative-config",
            "XDG_DATA_HOME": str(xdg_data) if absolute_override else "relative-data",
        }
    )
    state_dir = _install_for_setup(tmp_path, environment)
    result = _run_script(
        "configure-onshape.ps1",
        env=environment,
        input_text="fake-id\nfake-secret\n",
    )
    assert result.returncode == 0, result.stderr
    config_root = xdg_config if absolute_override else appdata
    token_root = xdg_data if absolute_override else localappdata
    assert (config_root / "onshape-mcp" / "config.toml").is_file()
    token_path = token_root / "onshape-mcp" / "tokens.json"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("{}", encoding="utf-8")
    _install_for_setup(tmp_path, environment)
    state = json.loads((state_dir / "install.json").read_text(encoding="utf-8"))
    assert state["config_present"] is True
    assert state["tokens_present"] is True


@pytest.mark.parametrize(
    ("node_version", "include_node"),
    [("v21.0.0", True), ("v24.0.0", False)],
)
def test_setup_scripts_use_fake_node_and_reject_old_or_missing_node(
    tmp_path: Path,
    node_version: str,
    include_node: bool,
) -> None:
    environment, _, _ = _with_fake_tools(
        tmp_path,
        node_version=node_version,
        include_node=include_node,
        only_fake_path=True,
    )

    for script in ("configure-onshape.ps1", "login-onshape.ps1"):
        result = _run_script(script, env=environment)
        assert result.returncode != 0
        assert "Node.js 22" in result.stderr


def test_configure_preserves_toml_sections_and_escapes_credentials(
    tmp_path: Path,
) -> None:
    environment, _, _ = _with_fake_tools(tmp_path)
    appdata = tmp_path / "appdata"
    environment["APPDATA"] = str(appdata)
    _install_for_setup(tmp_path, environment)
    config_dir = appdata / "onshape-mcp"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.toml"
    config_path.write_bytes(
        (
            '[general]\r\nkeep = "yes"\r\n\r\n'
            '[auth]\r\nprovider = "onshape"\r\n'
            'client_id = "old-id"\r\nclient_secret = "old-secret"\r\n'
            'redirect_uri = "old-callback"\r\n\r\n'
            "[other]\r\nanswer = 42\r\n"
        ).encode("utf-8")
    )

    result = _run_script(
        "configure-onshape.ps1",
        env=environment,
        input_text='id"quoted\\path\nsec"ret\\path\n',
    )

    assert result.returncode == 0, result.stderr
    config = config_path.read_text(encoding="utf-8")
    assert "[general]" in config
    assert 'keep = "yes"' in config
    assert "[auth]" in config
    assert 'provider = "onshape"' in config
    assert "[other]" in config
    assert "answer = 42" in config
    assert 'client_id = "id\\"quoted\\\\path"' in config
    assert 'client_secret = "sec\\"ret\\\\path"' in config
    assert config.count("client_id =") == 1
    assert config.count("client_secret =") == 1
    assert config.count("redirect_uri =") == 1


def test_configure_atomic_failure_keeps_existing_config_and_cleans_temp(
    tmp_path: Path,
) -> None:
    environment, _, _ = _with_fake_tools(tmp_path)
    appdata = tmp_path / "appdata"
    environment["APPDATA"] = str(appdata)
    config_dir = appdata / "onshape-mcp"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.toml"
    original = '[auth]\nclient_id = "original"\n'
    config_path.write_text(original, encoding="utf-8")
    config_path.chmod(stat.S_IREAD)

    result = _run_script(
        "configure-onshape.ps1",
        env=environment,
        input_text="new-id\nnew-secret\n",
    )

    config_path.chmod(stat.S_IWRITE | stat.S_IREAD)
    assert result.returncode != 0
    assert config_path.read_text(encoding="utf-8") == original
    assert not list(config_dir.glob(".config.toml.*.tmp"))
    assert not list(config_dir.glob(".config.toml.*.bak"))


def test_skip_runtime_install_without_venv_falls_back_to_importable_python(
    tmp_path: Path,
) -> None:
    mini_repo = tmp_path / "repo-without-venv"
    shutil.copytree(
        REPO_ROOT,
        mini_repo,
        ignore=shutil.ignore_patterns(
            ".venv",
            ".git",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
        ),
    )
    assert not (mini_repo / ".venv").exists()
    codex_home = tmp_path / "codex"
    state_dir = tmp_path / "state"
    environment, _, fake_bin = _with_fake_tools(tmp_path)
    environment["PATH"] = (
        f"{Path(sys.executable).parent}{os.pathsep}{fake_bin}"
        f"{os.pathsep}{os.environ['PATH']}"
    )

    install = _run_script(
        "install.ps1",
        "-HostTarget",
        "codex",
        "-SkipRuntimeInstall",
        "-CodexHome",
        str(codex_home),
        "-StateDir",
        str(state_dir),
        env=environment,
        cwd=tmp_path,
        repo_root=mini_repo,
    )

    assert install.returncode == 0, install.stderr
    state = json.loads((state_dir / "install.json").read_text(encoding="utf-8-sig"))
    assert Path(state["repo_root"]).resolve() == mini_repo.resolve()
    assert Path(state["python_path"]).is_file()
    launcher = (
        codex_home / "skills" / "onshape-engineering" / "scripts" / "onshape-agent.ps1"
    )
    launcher_environment = dict(environment)
    launcher_environment["ONSHAPE_AGENT_STATE_DIR"] = str(state_dir)
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-InputFormat",
            "Text",
            "-File",
            str(launcher),
            "doctor",
            "--json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=launcher_environment,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "READY_OFFLINE"
