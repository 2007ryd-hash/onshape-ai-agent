# Installable Dual-Host V1.1 Design

## Purpose

Turn the existing supervised CAD workflow into an open-source package that a
user can install locally and invoke from either Codex or Claude Code. The host
agent supplies reasoning; this project must not require an OpenAI or Anthropic
API key.

V1.1 prioritises a working installation and a visible end-to-end result. It
retains only the minimum execution boundary needed to prevent accidental
workspace deletion or mutation outside the selected document.

## User Experience

The repository supports Windows first. A user clones the repository and runs:

```powershell
.\scripts\install.ps1 -HostTarget all
```

The installer creates a project-owned Python virtual environment, installs the
Python package, and installs or links the host integration requested by the
user. Supported host targets are `codex`, `claude`, and `all`.

After restarting or reloading the host, a user can ask naturally for CAD work
or invoke the installed skill explicitly. The host loads the same shared CAD
workflow and calls the local `onshape-agent` CLI. No provider SDK is embedded
in the Python package.

## Product Boundary

### Included in V1.1

- one shared `onshape-engineering` skill for Codex and Claude Code;
- a Codex plugin manifest and repository marketplace entry;
- a Claude Code plugin manifest and repository marketplace entry;
- host-specific specialist agent definitions where the host supports them;
- a Windows PowerShell installer and uninstaller;
- a deterministic environment/status command;
- an offline end-to-end example that produces engineering, CAD, drawing, and
  verification artifacts;
- installation, manifest, CLI, and end-to-end tests;
- public, course-independent documentation.

### Excluded from V1.1

- live Onshape writes;
- embedded OpenAI, Anthropic, or other LLM API clients;
- autonomous engineering sign-off;
- production finite-element analysis;
- automatic publication to public plugin marketplaces;
- macOS and Linux installation scripts.

## Repository Layout

```text
.agents/plugins/marketplace.json
.claude-plugin/marketplace.json
plugins/onshape-engineering-agent/.codex-plugin/plugin.json
plugins/onshape-engineering-agent/.claude-plugin/plugin.json
plugins/onshape-engineering-agent/skills/onshape-engineering/SKILL.md
plugins/onshape-engineering-agent/skills/onshape-engineering/agents/openai.yaml
plugins/onshape-engineering-agent/skills/onshape-engineering/references/artifact-contracts.md
plugins/onshape-engineering-agent/agents/engineering-agent.md
plugins/onshape-engineering-agent/agents/cad-agent.md
plugins/onshape-engineering-agent/agents/drawing-agent.md
plugins/onshape-engineering-agent/agents/visual-qa-agent.md
scripts/install.ps1
scripts/uninstall.ps1
examples/simple-bracket/request.json
src/onshape_agent/doctor.py
tests/test_distribution.py
tests/test_doctor.py
tests/test_install_scripts.py
```

The canonical plugin bundle is `plugins/onshape-engineering-agent`. Both host
formats point to that one directory, so shared skills and agent definitions are
not duplicated. The repository root remains the Python package and installer.

## Host Integration

### Codex

Codex discovers the plugin through the bundle's `.codex-plugin/plugin.json` and
the repository marketplace entry. The skill includes `agents/openai.yaml` for
UI metadata and normal implicit invocation.

The installer also supports a direct development installation by creating a
directory link in the user's Codex skills directory. It must not overwrite an
unrelated existing skill without `-Force`.

### Claude Code

Claude Code discovers `.claude-plugin/plugin.json`, `skills/`, and `agents/`
from the same bundle root. The repository marketplace file allows installation
from GitHub after the repository becomes public. Local development uses Claude
Code's plugin directory or a directory link managed by the installer.

### Shared Skill

The skill triggers for mechanical CAD modelling, assemblies, drawings,
geometry verification, and engineering-to-CAD planning. It routes work by
artifact rather than by free-form conversations between specialist agents.

The skill tells the host to:

1. extract requirements and label unknown dimensions;
2. create or validate authoritative JSON artifacts;
3. invoke the local CLI for deterministic planning and verification;
4. route repair through the main host agent;
5. report exactly which results are simulated or live.

## Local Runtime

The installer creates `.venv` in the cloned repository and installs the package
in editable mode. Host integrations call the interpreter through a small
repository-relative launcher so installation does not depend on a global
Python command after setup.

The Python package gains a `doctor` command. It reports machine-readable JSON
covering Python compatibility, package import, writable output location, skill
files, host manifests, and whether an Onshape transport is configured. A
missing live transport is `not_configured`, not an error for V1.1.

## Offline Result

The existing demo is retained, but V1.1 adds a named `simple-bracket` example
whose request is stored in the repository. Running it creates a versioned run
directory with:

```text
manifest.json
events.jsonl
artifacts/task_graph_v1.json
artifacts/execution_plan_v1.json
artifacts/execution_report_v1.json
artifacts/drawing_plan_v1.json
artifacts/visual_report_v1.json
artifacts/diagnosis_v1.json
```

The command reports `network_request_sent=false` and `visual_mode=simulated`.
This is a genuine workflow result but not a claim that Onshape was modified.

## Minimal Execution Boundary

V1.1 keeps three hard constraints:

- `delete_workspace` remains unavailable;
- an execution target must remain inside the selected document scope;
- unknown or unapproved dimensions cannot be dispatched.

Other hardening work is deferred unless required for the installer or offline
result to function.

## Testing

Tests must prove:

- both plugin manifests parse and name the same product;
- both marketplace files reference the repository plugin root;
- the shared skill validates and contains no unfinished placeholders;
- installer target selection is deterministic and refuses unrelated existing
  destinations without `-Force`;
- uninstallation removes only links or directories owned by this project;
- `doctor --json` succeeds without provider API keys;
- the simple-bracket example produces the complete artifact set;
- existing Gateway denial and repair-routing tests continue to pass.

The implementation follows red-green-refactor. The full suite and Ruff must be
clean before publication.

## Release Result

V1.1 is ready when a fresh Windows checkout can install for Codex, Claude Code,
or both; each host can discover the shared skill; and the documented offline
example completes without any LLM provider API key. Publication will occur
only after local/remote state and the release commit are verified.
