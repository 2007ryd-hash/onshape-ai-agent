# Onshape authentication on Windows

V1.11.1 uses the pinned upstream `onshape-mcp@0.5.2` process for OAuth and
read-only Onshape requests. The host supplies the language model; this project
does not require an OpenAI or Anthropic API key.

## First-time setup

Install Python 3.12 with the Windows `py` launcher, Node.js 22 or newer with
`npx.cmd`, Git, and your chosen Codex or Claude Code host. From the repository
root, install the runtime and host integration:

```powershell
.\scripts\install.ps1 -HostTarget all
```

Use `-HostTarget codex` or `-HostTarget claude` for just one host. The installer
verifies the pinned upstream package but does not configure OAuth or log in.

Each third-party user must register their own Onshape OAuth application and
use their own client ID and client secret. This repository distributes no
shared OAuth application secret. In that application's settings, register
this exact redirect URI:

```text
http://localhost:18338/callback
```

Then run, in order:

```powershell
.\scripts\configure-onshape.ps1
.\scripts\login-onshape.ps1
.\.venv\Scripts\python.exe -m onshape_agent.cli doctor --live --json --repo-root .
```

The configure script prompts for a client ID and a masked client secret in
your terminal. Enter these locally rather than in chat, a source file, or a
command-line argument. It updates the upstream TOML auth fields while
preserving unrelated settings. Configure does not launch browser consent.

The login script explicitly runs the pinned upstream `auth login` flow. Sign
in to Onshape in the browser and grant consent once for your application.
Upstream stores and reuses the resulting credentials; this does not guarantee
permanent authorization. If access is revoked or cannot be refreshed, run
login again. Child login output is suppressed by the wrapper; its completion
message alone is not a live diagnostic result.

The live doctor validates the existing session. It does not silently invoke
login. A successful check reports `READY_LIVE` with
`network_request_sent=true` and `readback_verified=true`. This establishes
the authentication probe's result, not CAD write capability or successful
creation of a model.

## Local storage and offline checks

Default Windows locations are:

| Purpose | Location |
|---|---|
| Agent installation metadata | `%LOCALAPPDATA%\onshape-engineering-agent\install.json` |
| Upstream OAuth configuration | `%APPDATA%\onshape-mcp\config.toml` |
| Upstream OAuth tokens | `%LOCALAPPDATA%\onshape-mcp\tokens.json` |

Absolute `XDG_CONFIG_HOME` and `XDG_DATA_HOME` override the upstream config
and token base directories respectively, including on Windows. Relative XDG
values are ignored. Configuration, installation checks, and login use the
same paths; the agent installation metadata path is separate.

The upstream configuration contains your client secret, and tokens are also
sensitive. Keep these files out of the repository and shared diagnostics.
The local auth status command checks file presence without reading credential
values or making a network request:

```powershell
.\.venv\Scripts\python.exe -m onshape_agent.cli auth status --json
.\.venv\Scripts\python.exe -m onshape_agent.cli doctor --json --repo-root .
```

Local `READY_LOCAL` and the presence flags do not prove that credentials are
valid: `authenticated` is `null` and `verification` is `unverified`.
Likewise, `READY_OFFLINE` means the offline installation checks passed;
`onshape_transport=not_configured` in that report describes the offline mode,
not a failed live authentication check. Use `doctor --live` to validate the
existing Onshape session.

## Read-only use and failures

```powershell
.\.venv\Scripts\python.exe -m onshape_agent.cli live list-documents --limit 1 --json
.\.venv\Scripts\python.exe -m onshape_agent.cli live read-document --document-id YOUR_DOCUMENT_ID --json
```

Replace the placeholder with the exact selected document ID. Document
discovery accepts a limit of 1 through 100. Live operations emit body-free
receipts with status, network and verification flags, and bounded evidence
summaries. The gateway's live path permits only its allowlisted reads. OAuth
consent does not enable model creation, sketch writes, sharing, deletion, or
Drawing creation through this release.

If the live doctor returns `AUTH_REQUIRED`, complete configuration and explicit
login, then retry it. For `NOT_READY`, inspect the report's failed checks and
safe error code; verify the runtime, Node.js, pinned package availability,
and connectivity. For browser callback problems, verify the exact registered
URI above and availability of local port 18338. Do not paste credential files
to diagnose an error.

The `simple-bracket` example remains offline even after login and must retain
`network_request_sent=false` and `visual_mode=simulated`. These instructions
document the current implementation. Acceptance on 2026-09-05 verified live
authentication and document reads with an existing local OAuth grant; a newly
registered third-party application was not tested in that run.
