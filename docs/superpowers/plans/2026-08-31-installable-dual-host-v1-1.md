# Installable Dual-Host V1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Windows-first, locally installable CAD workflow that Codex and Claude Code can discover and run without an OpenAI or Anthropic API key.

**Architecture:** Keep the existing Python package as the deterministic runtime. Package one shared skill and specialist-agent set under `plugins/onshape-engineering-agent`, add thin Codex and Claude manifests, and use PowerShell to install the runtime plus host links. V1.1 remains offline and proves the complete artifact workflow with a named example.

**Tech Stack:** Python 3.12, Pydantic, Typer, pytest, PowerShell 7/Windows PowerShell, Agent Skills Markdown, Codex and Claude Code plugin manifests.

---

## File Map

- `plugins/onshape-engineering-agent/`: canonical bundle copied or linked by both hosts.
- `skills/onshape-engineering/SKILL.md`: shared routing and execution workflow.
- `agents/*.md`: host-discoverable specialist role contracts.
- `src/onshape_agent/doctor.py`: deterministic installation inspection.
- `src/onshape_agent/examples.py`: named example loading and execution.
- `scripts/install.ps1`: runtime and host integration installation.
- `scripts/uninstall.ps1`: ownership-aware host-link removal.
- `tests/test_distribution.py`: manifests, marketplace, skill, and agent contracts.
- `tests/test_doctor.py`: machine-readable environment diagnostics.
- `tests/test_examples.py`: complete offline artifact result.
- `tests/test_install_scripts.py`: static and subprocess installer behavior.

### Task 1: Create the distributable plugin bundle

**Files:**
- Create: `plugins/onshape-engineering-agent/.codex-plugin/plugin.json`
- Create: `plugins/onshape-engineering-agent/.claude-plugin/plugin.json`
- Create: `.agents/plugins/marketplace.json`
- Create: `.claude-plugin/marketplace.json`
- Create: `LICENSE`
- Create: `tests/test_distribution.py`

- [ ] **Step 1: Write failing manifest tests**

Create tests that load all four JSON files and assert:

```python
PLUGIN_NAME = "onshape-engineering-agent"

def test_host_manifests_identify_same_plugin(repo_root: Path) -> None:
    codex = load_json(repo_root / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json")
    claude = load_json(repo_root / "plugins" / PLUGIN_NAME / ".claude-plugin" / "plugin.json")
    assert codex["name"] == claude["name"] == PLUGIN_NAME
    assert codex["version"] == claude["version"] == "0.2.0"

def test_marketplaces_reference_canonical_bundle(repo_root: Path) -> None:
    codex = load_json(repo_root / ".agents" / "plugins" / "marketplace.json")
    claude = load_json(repo_root / ".claude-plugin" / "marketplace.json")
    assert codex["plugins"][0]["source"]["path"] == "./plugins/onshape-engineering-agent"
    assert claude["plugins"][0]["source"] == "./plugins/onshape-engineering-agent"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_distribution.py -q
```

Expected: failures because the manifests do not exist.

- [ ] **Step 3: Add minimal valid manifests and Apache-2.0 license**

Use `onshape-engineering-agent`, version `0.2.0`, repository
`https://github.com/2007ryd-hash/onshape-ai-agent`, and one skills path
`./skills/`. Do not declare MCP, hooks, or apps. The Codex marketplace entry
must contain `AVAILABLE`, `ON_INSTALL`, and category `Developer Tools`. The
Claude marketplace uses the same canonical bundle source.

- [ ] **Step 4: Validate and verify GREEN**

Run the focused tests and the Codex plugin validator:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_distribution.py -q
py -3.12 C:\Users\2007r\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py plugins\onshape-engineering-agent
```

Expected: all tests pass and validator exits zero.

- [ ] **Step 5: Commit**

```powershell
git add LICENSE .agents .claude-plugin plugins tests/test_distribution.py
git commit -m "feat: add dual-host plugin distribution"
```

### Task 2: Add the shared skill and specialist agents

**Files:**
- Create: `plugins/onshape-engineering-agent/skills/onshape-engineering/SKILL.md`
- Create: `plugins/onshape-engineering-agent/skills/onshape-engineering/agents/openai.yaml`
- Create: `plugins/onshape-engineering-agent/skills/onshape-engineering/references/artifact-contracts.md`
- Create: `plugins/onshape-engineering-agent/agents/engineering-agent.md`
- Create: `plugins/onshape-engineering-agent/agents/cad-agent.md`
- Create: `plugins/onshape-engineering-agent/agents/drawing-agent.md`
- Create: `plugins/onshape-engineering-agent/agents/visual-qa-agent.md`
- Modify: `tests/test_distribution.py`

- [ ] **Step 1: Add failing skill-contract tests**

Assert the skill exists, has only `name` and `description` frontmatter, has no
unfinished scaffold markers, names the local CLI, and links the artifact reference. Assert each
agent file declares a unique name and explicitly produces JSON/Markdown
artifacts instead of calling Onshape directly.

- [ ] **Step 2: Run tests and verify RED**

Expected: missing skill and agent files.

- [ ] **Step 3: Write the smallest useful shared skill**

The skill must route these requests: CAD parts, assemblies, mates, engineering
drawings, structured engineering analysis, and geometry verification. Its body
must require this sequence:

```text
intake -> requirement artifact -> main review -> CAD execution plan
-> local onshape-agent command -> drawing plan -> verification -> final review
```

It must label `UNKNOWN`, `NEEDS_CONFIRMATION`, and `ASSUMPTION`; treat JSON as
authoritative; disclose simulated/live status; and never instruct a worker to
call Onshape directly.

- [ ] **Step 4: Write four bounded agent contracts**

Each agent file states allowed inputs and exact outputs:

```text
engineering-agent -> engineering_model.json, analysis_result.json
cad-agent         -> cad_spec.json, execution_plan.json
drawing-agent     -> drawing_plan.json
visual-qa-agent   -> visual_report.json
```

The main host agent owns approval and repair routing.

- [ ] **Step 5: Validate skill and run tests**

```powershell
py -3.12 C:\Users\2007r\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\onshape-engineering-agent\skills\onshape-engineering
.\.venv\Scripts\python.exe -m pytest tests/test_distribution.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add plugins tests/test_distribution.py
git commit -m "feat: add shared CAD skill and specialist agents"
```

### Task 3: Add deterministic installation diagnostics

**Files:**
- Create: `src/onshape_agent/doctor.py`
- Modify: `src/onshape_agent/cli.py`
- Create: `tests/test_doctor.py`

- [ ] **Step 1: Write failing doctor tests**

Use a temporary repository root and assert:

```python
report = inspect_installation(repo_root)
assert report.status == "READY_OFFLINE"
assert report.provider_api_key_required is False
assert report.onshape_transport == "not_configured"
assert all(check.status == "PASS" for check in report.checks)
```

Also invoke `doctor --json --repo-root <path>` and parse stdout as JSON.

- [ ] **Step 2: Run tests and verify RED**

Expected: import or command failure because `doctor` does not exist.

- [ ] **Step 3: Implement typed diagnostics**

Define strict Pydantic models:

```python
class DoctorCheck(StrictModel):
    name: str
    status: Literal["PASS", "FAIL"]
    detail: str

class DoctorReport(StrictModel):
    status: Literal["READY_OFFLINE", "NOT_READY"]
    provider_api_key_required: Literal[False] = False
    onshape_transport: Literal["not_configured"] = "not_configured"
    checks: list[DoctorCheck]
```

Check Python 3.12+, package import, both manifests, shared skill, example request,
and writable output root. Do not read or print environment secrets.

- [ ] **Step 4: Add CLI command and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_doctor.py -q
.\.venv\Scripts\python.exe -m onshape_agent.cli doctor --json
```

- [ ] **Step 5: Commit**

```powershell
git add src/onshape_agent tests/test_doctor.py
git commit -m "feat: add offline installation doctor"
```

### Task 4: Add the named simple-bracket result

**Files:**
- Create: `examples/simple-bracket/request.json`
- Create: `src/onshape_agent/examples.py`
- Modify: `src/onshape_agent/cli.py`
- Modify: `src/onshape_agent/demo.py`
- Create: `tests/test_examples.py`

- [ ] **Step 1: Write failing end-to-end test**

Invoke `example simple-bracket --output <tmp>` and assert the returned summary
contains `example=simple-bracket`, `network_request_sent=false`, and
`visual_mode=simulated`. Assert the run contains all seven expected artifacts,
including `drawing_plan_v1.json`.

- [ ] **Step 2: Run test and verify RED**

Expected: unknown command or missing drawing artifact.

- [ ] **Step 3: Add an approved example request**

The request describes a 60 x 40 x 8 mm bracket plate with four 4 mm corner
holes offset 6 mm from adjacent edges. All values are millimetres and `KNOWN`.

- [ ] **Step 4: Implement example loading and drawing artifact generation**

Load only names matching `[a-z0-9-]+`, resolve under `examples/`, reject unknown
examples, and call the offline pipeline. Extend the pipeline to write a
third-angle `DrawingPlan` with front, top, right, and isometric views.

- [ ] **Step 5: Verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_examples.py tests/test_cli.py -q
.\.venv\Scripts\python.exe -m onshape_agent.cli example simple-bracket --output runs
```

- [ ] **Step 6: Commit**

```powershell
git add examples src/onshape_agent tests
git commit -m "feat: add simple bracket workflow example"
```

### Task 5: Add Windows installation and uninstallation

**Files:**
- Create: `scripts/install.ps1`
- Create: `scripts/uninstall.ps1`
- Create: `tests/test_install_scripts.py`

- [ ] **Step 1: Write failing subprocess tests**

In temporary HOME/CODEX_HOME/CLAUDE_CONFIG_DIR locations, run installer with
`-HostTarget codex`, `claude`, and `all`, plus `-SkipRuntimeInstall`. Assert the
expected directory links or copies exist. Pre-create an unrelated destination
and assert install fails without `-Force`. Run uninstall and assert it removes
only project-owned destinations.

- [ ] **Step 2: Run tests and verify RED**

Expected: scripts are missing.

- [ ] **Step 3: Implement deterministic installer**

Parameters:

```powershell
param(
    [ValidateSet('codex','claude','all')][string]$HostTarget = 'all',
    [switch]$Force,
    [switch]$SkipRuntimeInstall,
    [string]$CodexHome,
    [string]$ClaudeConfigDir
)
```

Resolve the repository from `$PSScriptRoot`; create `.venv` with `py -3.12` and
install `-e .` unless skipped. Prefer a directory junction on Windows and fall
back to a copy. Write an ownership marker containing the canonical repository
path. Refuse an existing destination whose marker does not match unless
`-Force` is supplied.

- [ ] **Step 4: Implement ownership-aware uninstaller**

Use the same target resolution. Remove only destinations with the matching
ownership marker. Do not remove the repository `.venv` unless an explicit
`-RemoveRuntime` switch is supplied.

- [ ] **Step 5: Verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_install_scripts.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add scripts tests/test_install_scripts.py
git commit -m "feat: add Windows dual-host installer"
```

### Task 6: Public documentation, project log, and release verification

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_LOG.md`
- Modify: `PROJECT_MEMORY.md`
- Create: `docs/project-log/2026-08-31-installable-v1-1.md`

- [ ] **Step 1: Rewrite README around user outcomes**

Lead with clone/install/use. Explain that no LLM API key is required, Onshape
OAuth is separate, and V1.1's included example is offline. Include commands for
Codex, Claude Code, `doctor`, example execution, testing, and uninstalling.

- [ ] **Step 2: Record implementation evidence and reusable pitfalls**

Log worktree setup, manifest validation, installer behavior, test counts, and
the exact boundary between offline success and live Onshape work.

- [ ] **Step 3: Run the full release gate**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
py -3.12 C:\Users\2007r\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py plugins\onshape-engineering-agent
py -3.12 C:\Users\2007r\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\onshape-engineering-agent\skills\onshape-engineering
.\.venv\Scripts\python.exe -m onshape_agent.cli doctor --json
.\.venv\Scripts\python.exe -m onshape_agent.cli example simple-bracket --output runs
```

Expected: tests and Ruff exit zero; both validators exit zero; doctor reports
`READY_OFFLINE`; example reports no network request and emits the complete
artifact set.

- [ ] **Step 4: Commit**

```powershell
git add README.md PROJECT_LOG.md PROJECT_MEMORY.md docs
git commit -m "docs: publish installable v1.1 workflow"
```

- [ ] **Step 5: Final review before GitHub publication**

Inspect `git diff main...HEAD`, run a lightweight secret scan, and verify no
runtime outputs or credentials are tracked. Merge only after spec compliance
and code-quality reviews are both clear.
