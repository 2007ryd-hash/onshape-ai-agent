# Live Onshape v1.11.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an installable `v1.11.0` that performs an explicit, authenticated, read-only Onshape connection and deterministic readback through the existing CAD Gateway.

**Architecture:** Keep model workers artifact-only. Add a bounded MCP stdio session and a fixed semantic-operation transport behind the deterministic Gateway; reuse pinned `onshape-mcp@0.5.2` for OAuth and REST access. Offline examples remain permanently network-free, while live commands require explicit opt-in and verified readback.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, PowerShell, pytest, Ruff, MCP JSON-RPC over stdio, `onshape-mcp@0.5.2`.

---

## File Structure

- Create `src/onshape_agent/mcp_stdio.py`: bounded JSON-RPC stdio lifecycle.
- Create `src/onshape_agent/live_transport.py`: fixed semantic-to-MCP operation map and safe receipts.
- Create `src/onshape_agent/live_service.py`: explicit auth probe and readback application service.
- Create `tests/fake_mcp_server.py`: deterministic fake child process used as protocol oracle.
- Create `tests/test_mcp_stdio.py`: framing, lifecycle, timeout, size, and error tests.
- Create `tests/test_live_transport.py`: operation allowlist, scope, and response normalization tests.
- Create `tests/test_live_service.py`: live doctor and readback behavior tests.
- Modify `src/onshape_agent/contracts.py`: typed execution mode, scope, receipts, and report evidence.
- Modify `src/onshape_agent/gateway.py`: whole-plan preflight, typed receipts, transport failure mapping.
- Modify `src/onshape_agent/policy.py`: separate live read allowlist and scope validation.
- Modify `src/onshape_agent/doctor.py`: offline/live status model and explicit live probe injection.
- Modify `src/onshape_agent/cli.py`: `auth status`, `doctor --live`, and bounded live read commands.
- Create `scripts/configure-onshape.ps1`: non-secret configuration guidance and hidden credential setup.
- Create `scripts/login-onshape.ps1`: pinned explicit OAuth login launcher.
- Modify `scripts/install.ps1`: pinned MCP dependency probe and next-step output.
- Modify `scripts/uninstall.ps1`: preserve upstream credentials by default.
- Modify `README.md` and create `docs/authentication.md`: exact third-party setup and trust boundary.
- Modify all version-bearing manifests and `src/onshape_agent/__init__.py`: consistent `1.11.0`.
- Modify `PROJECT_LOG.md` and `PROJECT_MEMORY.md`: implementation evidence and reusable pitfalls.

### Task 1: Version and Live Contracts

**Files:**
- Modify: `src/onshape_agent/contracts.py`
- Modify: `src/onshape_agent/__init__.py`
- Modify: `pyproject.toml`
- Modify: `plugins/onshape-engineering-agent/.codex-plugin/plugin.json`
- Modify: `plugins/onshape-engineering-agent/.claude-plugin/plugin.json`
- Modify: `.agents/plugins/marketplace.json`
- Modify: `.claude-plugin/marketplace.json`
- Test: `tests/test_contracts.py`
- Test: `tests/test_distribution.py`

- [ ] **Step 1: Write failing contract and version tests**

Add tests that instantiate a live scope and receipt and compare every manifest version:

```python
def test_live_scope_allows_missing_document_for_document_discovery():
    scope = OnshapeScope(stack="cad.onshape.com")
    assert scope.document_id is None


def test_transport_receipt_records_real_request_and_readback():
    receipt = TransportReceipt(
        operation="get_document",
        status="SUCCEEDED",
        network_request_sent=True,
        readback_verified=True,
        evidence_summary={"document_id_matches": True},
    )
    assert receipt.network_request_sent is True
    assert receipt.readback_verified is True


def test_all_distribution_versions_are_1_11_0():
    assert package_version() == "1.11.0"
    assert module_version() == "1.11.0"
    assert set(plugin_versions()) == {"1.11.0"}
```

- [ ] **Step 2: Verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_contracts.py tests/test_distribution.py`

Expected: FAIL because `OnshapeScope` and `TransportReceipt` do not exist and versions are `0.1.0`/`0.2.0`.

- [ ] **Step 3: Implement the minimal strict models**

Add strict models with literal modes and safe summary fields:

```python
class OnshapeScope(StrictModel):
    stack: Literal["cad.onshape.com"] = "cad.onshape.com"
    document_id: str | None = None
    wvm: Literal["w", "v", "m"] | None = None
    wvm_id: str | None = None
    element_id: str | None = None


class TransportReceipt(StrictModel):
    operation: str
    status: Literal["SUCCEEDED", "FAILED"]
    network_request_sent: bool
    readback_verified: bool
    evidence_summary: dict[str, bool | int | float | str] = Field(default_factory=dict)
    error_code: str | None = None
```

`document_id` is optional so the scope can represent bounded document
discovery. Operations that require a document must validate that requirement
at the operation boundary in Task 3 rather than rejecting the discovery scope
when it is constructed.

Set every version-bearing source to `1.11.0`.

- [ ] **Step 4: Verify GREEN and commit**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_contracts.py tests/test_distribution.py`

Expected: PASS.

Commit: `git commit -am "feat: define live transport contracts"`

### Task 2: Bounded MCP Stdio Session

**Files:**
- Create: `src/onshape_agent/mcp_stdio.py`
- Create: `tests/fake_mcp_server.py`
- Create: `tests/test_mcp_stdio.py`

- [ ] **Step 1: Write failing lifecycle and error tests**

Use the fake child script to assert initialize/initialized ordering, tool result parsing, timeout, oversized response, JSON-RPC error, and process cleanup:

```python
def test_session_initializes_then_calls_tool(fake_mcp_command):
    with McpStdioSession(fake_mcp_command, timeout_seconds=2) as session:
        result = session.call_tool("onshape_auth_status", {"validate": False})
    assert result == {"configured": True}


def test_session_times_out_without_leaking_server_output(hanging_mcp_command):
    with pytest.raises(McpTransportError, match="TRANSPORT_TIMEOUT"):
        with McpStdioSession(hanging_mcp_command, timeout_seconds=0.1) as session:
            session.call_tool("hang", {})
```

- [ ] **Step 2: Verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_mcp_stdio.py`

Expected: FAIL because `McpStdioSession` is absent.

- [ ] **Step 3: Implement minimal session**

Implement `subprocess.Popen(..., shell=False)`, a stdout reader queue, stderr drain thread, monotonic request IDs, newline-delimited UTF-8 JSON, `initialize`, `notifications/initialized`, bounded wait, maximum response bytes, generic sanitized error codes, and terminate/kill cleanup. Parse `structuredContent` first, then JSON text content; never include raw child stderr or response content in exceptions.

- [ ] **Step 4: Verify GREEN and negative control**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_mcp_stdio.py`

Expected: PASS.

Temporarily reverse the initialized notification order and rerun the lifecycle test; expected FAIL. Restore the implementation and rerun to PASS.

- [ ] **Step 5: Commit**

Commit: `git add src/onshape_agent/mcp_stdio.py tests/fake_mcp_server.py tests/test_mcp_stdio.py && git commit -m "feat: add bounded MCP stdio session"`

### Task 3: Fixed Live Read Transport

**Files:**
- Create: `src/onshape_agent/live_transport.py`
- Create: `tests/test_live_transport.py`

- [ ] **Step 1: Write failing route and rejection tests**

Tests independently define the only supported mapping:

```python
EXPECTED_ENDPOINTS = {
    "list_documents": "getDocuments",
    "get_document": "getDocument",
    "list_workspaces": "getDocumentWorkspaces",
    "read_elements": "getElementsInDocument",
    "body_details": "getPartStudioBodyDetails",
    "bounding_boxes": "getPartStudioBoundingBoxes",
    "mass_properties": "getPartStudioMassProperties",
}


def test_get_document_uses_fixed_endpoint_and_approved_scope(session, scope):
    receipt = OnshapeMcpReadTransport(session, scope).read("get_document", {})
    assert session.last_call.name == "onshape_api_call"
    assert session.last_call.arguments == {
        "endpoint": "getDocument",
        "path_params": {"did": scope.document_id},
    }
    assert receipt.readback_verified is True


@pytest.mark.parametrize("operation", ["delete_workspace", "raw_http", "create_sketch"])
def test_unknown_or_mutating_operation_is_denied_before_mcp_call(operation, session, scope):
    with pytest.raises(LivePolicyDenied, match="OPERATION_DENIED"):
        OnshapeMcpReadTransport(session, scope).read(operation, {})
    assert session.calls == []
```

- [ ] **Step 2: Verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_live_transport.py`

Expected: FAIL because the transport is absent.

- [ ] **Step 3: Implement fixed routes and invariant checks**

The public API is only `auth_status()` and `read(operation, safe_parameters)`. Build all MCP arguments internally from `OnshapeScope`; reject caller-provided endpoint, URL, method, body, headers, file references, identifiers that differ from scope, invalid `wvm`, and list limits above 100. Produce receipts from explicit invariant checks rather than MCP success alone.

- [ ] **Step 4: Verify GREEN and mutation strength**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_live_transport.py`

Expected: PASS.

Replace `getDocument` with a known write endpoint in a temporary mutation and rerun the route test; expected FAIL. Restore and rerun to PASS.

- [ ] **Step 5: Commit**

Commit: `git add src/onshape_agent/live_transport.py tests/test_live_transport.py && git commit -m "feat: add allowlisted Onshape read transport"`

### Task 4: Gateway Live Preflight and Receipts

**Files:**
- Modify: `src/onshape_agent/policy.py`
- Modify: `src/onshape_agent/gateway.py`
- Modify: `src/onshape_agent/contracts.py`
- Modify: `tests/test_gateway.py`

- [ ] **Step 1: Write failing whole-plan and readback tests**

```python
def test_live_gateway_preflights_entire_plan_before_first_request():
    transport = FakeLiveTransport()
    report = CadGateway(transport).execute(plan_with_valid_read_then_delete())
    assert report.status == "DENIED"
    assert transport.calls == []


def test_live_gateway_requires_verified_readback():
    transport = FakeLiveTransport(readback_verified=False)
    report = CadGateway(transport).execute(valid_live_read_plan())
    assert report.status == "FAILED"
    assert report.code == "VERIFICATION_FAILED"
```

- [ ] **Step 2: Verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_gateway.py`

Expected: FAIL because the Gateway ignores dispatch results and has no live semantics.

- [ ] **Step 3: Implement minimal live execution semantics**

Preflight every action and scope before dispatch. Collect typed receipts. Derive `network_request_sent` from receipts, not a transport class flag. Map sanitized transport exceptions to `FAILED`; require every live receipt to have successful verified readback. Preserve current offline execution behavior.

- [ ] **Step 4: Verify GREEN and commit**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_gateway.py tests/test_examples.py`

Expected: PASS, including permanent offline behavior.

Commit: `git add src/onshape_agent/contracts.py src/onshape_agent/policy.py src/onshape_agent/gateway.py tests/test_gateway.py && git commit -m "feat: enforce live gateway readback"`

### Task 5: Explicit Live Doctor and CLI

**Files:**
- Create: `src/onshape_agent/live_service.py`
- Modify: `src/onshape_agent/doctor.py`
- Modify: `src/onshape_agent/cli.py`
- Create: `tests/test_live_service.py`
- Modify: `tests/test_doctor.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing offline/live command tests**

```python
def test_default_doctor_never_constructs_live_session(monkeypatch, tmp_path):
    monkeypatch.setattr(live_service, "open_session", fail_if_called)
    result = runner.invoke(app, ["doctor", "--json", "--repo-root", str(tmp_path)])
    assert result.exit_code in {0, 1}
    assert "network_request_sent" not in result.exception_text


def test_live_doctor_returns_ready_live_from_validated_probe(fake_live_service, repo_root):
    result = runner.invoke(app, ["doctor", "--live", "--json", "--repo-root", str(repo_root)])
    report = json.loads(result.stdout)
    assert report["status"] == "READY_LIVE"
    assert report["network_request_sent"] is True
```

- [ ] **Step 2: Verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_live_service.py tests/test_doctor.py tests/test_cli.py`

Expected: FAIL because live service and CLI options do not exist.

- [ ] **Step 3: Implement explicit commands**

Add injectable `LiveService` methods `auth_status()`, `list_documents(limit)`, and `read_document(document_id)`. Add `auth status --json`, `doctor --live --json`, `live list-documents --limit`, and `live read-document --document-id`. Commands open the pinned MCP only after explicit live selection and output safe summaries, never raw document payloads.

- [ ] **Step 4: Verify GREEN and commit**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_live_service.py tests/test_doctor.py tests/test_cli.py`

Expected: PASS.

Commit: `git add src/onshape_agent/live_service.py src/onshape_agent/doctor.py src/onshape_agent/cli.py tests/test_live_service.py tests/test_doctor.py tests/test_cli.py && git commit -m "feat: add explicit live doctor and read CLI"`

### Task 6: Third-Party Setup Scripts

**Files:**
- Create: `scripts/configure-onshape.ps1`
- Create: `scripts/login-onshape.ps1`
- Modify: `scripts/install.ps1`
- Modify: `scripts/uninstall.ps1`
- Modify: `tests/test_install_scripts.py`

- [ ] **Step 1: Write failing distribution-script tests**

Assert scripts pin `onshape-mcp@0.5.2`, use `npx.cmd`, never accept a client secret command-line parameter, never write it into `install.json`, and print the exact callback URI. Add a subprocess test with temporary homes and fake `npx.cmd` proving no credential appears in stdout/stderr.

- [ ] **Step 2: Verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_install_scripts.py`

Expected: FAIL because setup scripts are absent.

- [ ] **Step 3: Implement minimal PowerShell flow**

`configure-onshape.ps1` verifies Node 22+, prints `http://localhost:18338/callback`, prompts for client ID normally and client secret through `Read-Host -AsSecureString`, and writes the upstream config at `%APPDATA%\onshape-mcp\config.toml` without echoing values. `login-onshape.ps1` invokes only `npx.cmd --yes onshape-mcp@0.5.2 auth login`. Installer verifies the pinned package version and prints next steps. Uninstaller preserves upstream config/tokens and states that clearly.

- [ ] **Step 4: Verify GREEN and commit**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_install_scripts.py`

Expected: PASS.

Commit: `git add scripts tests/test_install_scripts.py && git commit -m "feat: add guided Onshape setup scripts"`

### Task 7: Documentation, Skill, and Disclosure

**Files:**
- Create: `docs/authentication.md`
- Modify: `README.md`
- Modify: `plugins/onshape-engineering-agent/skills/onshape-engineering/SKILL.md`
- Modify: `PROJECT_LOG.md`
- Modify: `PROJECT_MEMORY.md`
- Modify: `tests/test_distribution.py`

- [ ] **Step 1: Write failing documentation assertions**

Assert README documents clone/install/configure/login/doctor-live, the one-time user authorization requirement, upstream OAuth write scope, live-read-only Gateway boundary, offline fallback, Enterprise limitation, and exact disclosure fields.

- [ ] **Step 2: Verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_distribution.py`

Expected: FAIL because the live flow is undocumented.

- [ ] **Step 3: Write source-linked documentation**

Document Onshape OAuth registration and consent, `onshape-mcp@0.5.2`, local config/token locations, revoke/logout distinction, API-key fallback, safe troubleshooting, and what v1.11 does not yet mutate. Update the skill so only the host invokes explicit live commands and every live claim requires a receipt.

- [ ] **Step 4: Verify GREEN and commit**

Run: `\.\.venv\Scripts\python.exe -m pytest -q tests/test_distribution.py`

Expected: PASS.

Commit: `git add README.md docs/authentication.md plugins/onshape-engineering-agent/skills/onshape-engineering/SKILL.md PROJECT_LOG.md PROJECT_MEMORY.md tests/test_distribution.py && git commit -m "docs: explain live Onshape connection"`

### Task 8: Full Verification and Real Readback

**Files:**
- Modify only if a failing verification exposes a defect; add a failing regression test before any fix.

- [ ] **Step 1: Run the complete automated suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
py -3.12 C:\Users\2007r\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py plugins\onshape-engineering-agent
py -3.12 C:\Users\2007r\.codex\skills\.system\skill-creator\scripts\quick_validate.py plugins\onshape-engineering-agent\skills\onshape-engineering
git diff --check
```

Expected: all tests pass, both validators pass, and no diff whitespace errors.

- [ ] **Step 2: Verify offline mode is still offline**

Run:

```powershell
.\.venv\Scripts\python.exe -m onshape_agent.cli doctor --json --repo-root .
.\.venv\Scripts\python.exe -m onshape_agent.cli example simple-bracket --output runs --repo-root .
```

Expected: `READY_OFFLINE`; example reports `execution_mode=simulated` and `network_request_sent=false`.

- [ ] **Step 3: Perform explicit real authentication probe**

Run: `.\.venv\Scripts\python.exe -m onshape_agent.cli doctor --live --json --repo-root .`

Expected: `READY_LIVE`, `network_request_sent=true`, transport `onshape-mcp-stdio`, and no token or private payload in output. If `AUTH_REQUIRED`, run `scripts\login-onshape.ps1`, let the user grant access, then rerun.

- [ ] **Step 4: Perform one real bounded readback**

Run: `.\.venv\Scripts\python.exe -m onshape_agent.cli live list-documents --limit 1`

Expected: a safe summary with one or zero result identifiers, `network_request_sent=true`, and `readback_verified=true`; no mutation is sent.

- [ ] **Step 5: Run secret and repository preflight**

Run tracked-file scans for `.env`, token/config files, private keys, OAuth secrets, access keys, and authorization headers. Inspect `git status --short --branch` and `git log --oneline main..HEAD`.

Expected: no credential-bearing tracked file, only intended commits, clean worktree.

- [ ] **Step 6: Final integration commit**

If project log evidence changed after verification:

```powershell
git add PROJECT_LOG.md PROJECT_MEMORY.md
git commit -m "docs: record v1.11 verification"
```

Do not merge, push, tag, or publish until the main host reviews the diff and all fresh evidence.
