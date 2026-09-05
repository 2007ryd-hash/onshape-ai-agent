# Onshape Engineering Agent

An open-source, locally installed engineering-to-CAD workflow for Codex and
Claude Code.

The host agent does the reasoning. This repository supplies the shared CAD
skill, specialist agent contracts, deterministic Python runtime, run artifacts,
and installation scripts. It does **not** require an OpenAI or Anthropic API
key.

## V1.11.0 scope

- one shared CAD skill for Codex and Claude Code;
- Engineering, CAD, Drawing, and Visual QA specialist definitions;
- artifact-only coordination with JSON as authoritative state;
- a local deterministic CAD Gateway and append-only run log;
- a Windows installer and ownership-aware uninstaller;
- a named `simple-bracket` workflow producing a CAD plan and four-view Drawing
  plan;
- offline installation diagnostics through `doctor --json`;
- explicit OAuth setup and read-only live diagnostics through
  `onshape-mcp@0.5.2`, with bounded document discovery and document reads;
- an Apache-2.0 licensed foundation for future Onshape automation.

V1.11.0 adds an opt-in, read-only Onshape connection. It does not create or
modify live CAD models or Drawings. The included bracket example remains
offline and explicitly reports `network_request_sent=false` and
`visual_mode=simulated`. Acceptance testing on 2026-09-05 verified live
authentication, document discovery, and document ID readback using an existing
local OAuth grant. Every new installation must pass its own live doctor.

## Install on Windows

Requirements:

- Windows 10 or 11;
- Python 3.12 through the Windows `py` launcher;
- Node.js 22 or newer, including `npx.cmd`;
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
local runtime state under `%LOCALAPPDATA%\onshape-engineering-agent`. It also
checks the pinned `onshape-mcp@0.5.2` package through `npx.cmd`, which may need
network access to download the package. Installation does not start OAuth login.

Restart Codex or reload Claude Code plugins/skills after installation.

## Connect your Onshape account

Each third-party installation uses its own Onshape OAuth application and client
credentials. No shared OAuth client secret is distributed. Register the exact
callback URI `http://localhost:18338/callback`, then run these commands from the
repository root, in order:

```powershell
.\scripts\configure-onshape.ps1
.\scripts\login-onshape.ps1
.\.venv\Scripts\python.exe -m onshape_agent.cli doctor --live --json --repo-root .
```

Configure prompts locally for your OAuth client ID and masked client secret.
Login opens the explicit browser authorization flow: sign in and grant consent
for your application once. Later sessions reuse the upstream credentials;
revoked or expired authorization may require login again. The live doctor
validates the existing session and never initiates browser login itself.

Only a successful live report with `status=READY_LIVE`,
`network_request_sent=true`, and `readback_verified=true` confirms this check
for your installation. See [authentication and troubleshooting](docs/authentication.md)
for storage locations and failure states.

After that check, explicitly request bounded reads:

```powershell
.\.venv\Scripts\python.exe -m onshape_agent.cli live list-documents --limit 1 --json
.\.venv\Scripts\python.exe -m onshape_agent.cli live read-document --document-id YOUR_DOCUMENT_ID --json
```

Replace `YOUR_DOCUMENT_ID` with the exact document you intend to read. These
commands return safe receipts and evidence summaries, not raw response bodies.

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

Expected status when the local checks pass (this does not validate OAuth):

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

These files make each stage inspectable. Running this example after OAuth
login still produces a simulated result, not a live Onshape bracket.

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

1. semantic geometry resolution and read-back;
2. one idempotent, verified sketch write;
3. STEP/OpenCascade geometry verification;
4. instances, Mate Connectors, and Mates;
5. live Drawing generation;
6. structural solver and adaptive visual QA.

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
