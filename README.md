# Onshape Engineering Agent

An open-source, locally installed engineering-to-CAD workflow for Codex and
Claude Code.

The host agent does the reasoning. This repository supplies the shared CAD
skill, specialist agent contracts, deterministic Python runtime, run artifacts,
and installation scripts. It does **not** require an OpenAI or Anthropic API
key.

## What works in V1.1

- one shared CAD skill for Codex and Claude Code;
- Engineering, CAD, Drawing, and Visual QA specialist definitions;
- artifact-only coordination with JSON as authoritative state;
- a local deterministic CAD Gateway and append-only run log;
- a Windows installer and ownership-aware uninstaller;
- a named `simple-bracket` workflow producing a CAD plan and four-view Drawing
  plan;
- installation diagnostics through `doctor --json`;
- an Apache-2.0 licensed foundation for future Onshape automation.

V1.1 is an offline workflow release. It does not yet write to Onshape. Example
runs explicitly report `network_request_sent=false` and
`visual_mode=simulated`.

## Install on Windows

Requirements:

- Windows 10 or 11;
- Python 3.12 through the Windows `py` launcher;
- Codex, Claude Code, or both;
- Git.

```powershell
git clone https://github.com/2007ryd-hash/onshape-ai-agent.git
cd onshape-ai-agent
.\scripts\install.ps1 -HostTarget all
```

Install only one host:

```powershell
.\scripts\install.ps1 -HostTarget codex
.\scripts\install.ps1 -HostTarget claude
```

The installer creates `.venv`, installs the local Python package, registers the
shared skill, installs Claude specialist definitions when requested, and writes
local runtime state under `%LOCALAPPDATA%\onshape-engineering-agent`.

Restart Codex or reload Claude Code plugins/skills after installation.

## Use it

Ask naturally:

> Create a parametric bracket from these dimensions, produce a Drawing plan,
> and verify the result.

Or explicitly invoke `onshape-engineering` in the host.

The workflow first reports understood parts, dimensions, connections, and
unknowns. `UNKNOWN`, `NEEDS_CONFIRMATION`, and unapproved `ASSUMPTION` values
cannot be dispatched as CAD dimensions.

## Verify the installation

```powershell
.\.venv\Scripts\python.exe -m onshape_agent.cli doctor --json --repo-root .
```

Expected V1.1 status:

```json
{
  "status": "READY_OFFLINE",
  "provider_api_key_required": false,
  "onshape_transport": "not_configured"
}
```

## Run the included result

```powershell
.\.venv\Scripts\python.exe -m onshape_agent.cli example simple-bracket --output runs --repo-root .
```

The generated run contains:

```text
manifest.json
events.jsonl
artifacts/problem_brief_v1.json
artifacts/task_graph_v1.json
artifacts/execution_plan_v1.json
artifacts/execution_report_v1.json
artifacts/drawing_plan_v1.json
artifacts/visual_report_v1.json
artifacts/diagnosis_v1.json
```

These files make each stage inspectable and provide the contract for future
live Onshape execution.

## Uninstall

```powershell
.\scripts\uninstall.ps1 -HostTarget all
```

The uninstaller removes only installations carrying this repository's ownership
marker. It preserves unrelated user skills and agents. Add `-RemoveRuntime`
only when you also want to delete this clone's `.venv`.

## Develop and test

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Design and implementation records are under `docs/superpowers/`. Project
decisions and verification evidence are recorded in `PROJECT_LOG.md` and
`PROJECT_MEMORY.md`.

## Roadmap

1. read-only Onshape OAuth transport;
2. semantic geometry resolution and read-back;
3. one idempotent, verified sketch write;
4. STEP/OpenCascade geometry verification;
5. instances, Mate Connectors, and Mates;
6. live Drawing generation;
7. structural solver and adaptive visual QA.

The long-term architecture remains:

```text
Host Main Agent
  -> approved JSON artifacts
  -> CAD Agent execution proposal
  -> deterministic CAD Gateway
  -> Onshape transport
  -> deterministic read-back and verification
```

## License

Apache License 2.0. See `LICENSE`.
