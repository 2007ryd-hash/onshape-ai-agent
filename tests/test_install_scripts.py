from __future__ import annotations

import json
import os
import shutil
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
        str(REPO_ROOT / "scripts" / script),
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


def _fake_npx(tmp_path: Path) -> tuple[Path, Path]:
    """Create a harmless npx.cmd shim and return its bin and trace paths."""

    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    trace_path = tmp_path / "npx-args.txt"
    (bin_dir / "npx.cmd").write_text(
        "@echo off\r\n"
        ">\"%FAKE_NPX_TRACE%\" echo %*\r\n"
        "if \"%~3\"==\"--version\" echo 0.5.2\r\n"
        "exit /b 0\r\n",
        encoding="ascii",
    )
    return bin_dir, trace_path


def _with_fake_npx(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir, trace_path = _fake_npx(tmp_path)
    environment = dict(os.environ)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    environment["FAKE_NPX_TRACE"] = str(trace_path)
    return environment, trace_path


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
    launcher = (REPO_ROOT / "scripts" / "onshape-agent.ps1").read_text(
        encoding="utf-8"
    )

    assert "npx.cmd" in configure
    assert "npx.cmd" in login
    assert "onshape-mcp@0.5.2" in configure
    assert "onshape-mcp@0.5.2" in login
    assert "http://localhost:18338/callback" in configure
    assert "-AsSecureString" in configure
    assert "clientsecret" not in configure.lower().split("param", 1)[-1].split(
        ")", 1
    )[0]
    assert "install.json" not in configure
    assert "PYTHONPATH" in launcher


def test_configure_writes_only_upstream_config_without_echoing_secret(
    tmp_path: Path,
) -> None:
    environment, _ = _with_fake_npx(tmp_path)
    appdata = tmp_path / "appdata"
    localappdata = tmp_path / "localappdata"
    environment["APPDATA"] = str(appdata)
    environment["LOCALAPPDATA"] = str(localappdata)
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
    assert not list(tmp_path.glob("**/install.json"))


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
