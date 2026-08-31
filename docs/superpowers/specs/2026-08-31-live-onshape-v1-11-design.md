# Live Onshape v1.11.0 Design

## Objective

Release an installable, course-independent `v1.11.0` that lets a third party
clone the repository, install the Codex or Claude Code integration, complete a
one-time authorization step, and verify a real connection to their own Onshape
account. Model workers remain artifact-only and never receive credentials or
direct Onshape access.

The installer automates dependencies, configuration guidance, login launch,
and subsequent local credential reuse. It cannot silently authorize a new
Onshape account: Onshape requires the user to create or select credentials and
grant access.

## Selected Approach

Use the stable `onshape-mcp@0.5.2` local stdio server as an implementation
detail behind the deterministic CAD Gateway.

```text
Codex or Claude main host
        |
        v
approved immutable JSON artifacts
        |
        v
deterministic CAD Gateway
        |
        v
allowlisted Onshape MCP transport
        |
        v
local onshape-mcp 0.5.2
        |
        v
Onshape REST API
```

This is preferred over a new OAuth implementation because the selected MCP
already implements local OAuth login, refresh-token handling, API discovery,
and Windows support. Direct API-key access remains a documented fallback, not
the default. A hosted OAuth broker and a shared client secret are out of scope.

## Release Scope

### Included

- Pin and install or verify `onshape-mcp@0.5.2`.
- Provide explicit setup and login commands for user-owned OAuth credentials.
- Detect the local MCP configuration and token presence without reading or
  logging their values.
- Add a bounded MCP stdio client with initialization, request correlation,
  timeouts, response-size limits, stderr draining, and process cleanup.
- Add a live, read-only transport with a fixed semantic-operation map.
- Add live authentication validation using `onshape_auth_status` with
  validation enabled.
- Support deterministic reads for document discovery, document metadata,
  workspaces, elements, Part Studio body details, bounding boxes, and mass
  properties.
- Add an explicit live doctor and a selected-document readback smoke test.
- Record execution mode, actual network-request state, transport, receipts,
  and readback verification without storing private response bodies in logs.
- Preserve the network-free recording transport and simple-bracket example.
- Publish consistent version `1.11.0` across Python and plugin manifests.

### Excluded

- General write access, arbitrary Feature API calls, mates, drawing creation,
  deletion, sharing, permissions, or raw HTTP.
- Direct worker access to MCP, credentials, the browser, or Onshape.
- A shared OAuth secret embedded in the public repository.
- A hosted authentication service.
- A claim that Enterprise-specific base URLs work until tested explicitly.
- Automatic publication to GitHub before local and live acceptance tests pass.

The first live release proves a genuine, reproducible connection and verified
readback. Mutating CAD is the next independently reviewed slice.

## Authentication and Installation Experience

The supported Windows flow is:

```powershell
git clone https://github.com/2007ryd-hash/onshape-ai-agent.git
cd onshape-ai-agent
.\scripts\install.ps1 -HostTarget all
.\scripts\configure-onshape.ps1
.\scripts\login-onshape.ps1
.\scripts\onshape-agent.ps1 doctor --live --json
```

The setup script explains how to create a user-owned Onshape OAuth application
with the exact callback `http://localhost:18338/callback`. It collects the
client ID and secret without placing them in command-line arguments or project
files, then delegates the OAuth lifecycle to `onshape-mcp`. The login command
opens the authorization page and waits for the user's grant. Subsequent runs
reuse the local token managed by `onshape-mcp`.

The repository does not copy tokens into its install state or run artifacts.
Default doctor remains offline and never opens a browser. `doctor --live` is an
explicit network action and reports `AUTH_REQUIRED` when setup is incomplete.

Because `onshape-mcp@0.5.2` requests both `OAuth2Read` and `OAuth2Write`, the
credential itself is not read-only. The v1.11 Gateway nevertheless exposes only
fixed GET operations. Documentation must state this distinction accurately.

## Typed Contracts

`ExecutionPlan` gains an explicit mode and a typed Onshape scope. A live scope
contains only the approved stack identifier and optional document, workspace,
version or microversion, and element identifiers. An action cannot override
the scope with an arbitrary host, URL, method, header, or body.

The transport returns a receipt instead of an unstructured dictionary:

```json
{
  "operation": "get_document",
  "status": "SUCCEEDED",
  "network_request_sent": true,
  "readback_verified": true,
  "evidence_summary": {
    "document_id_matches": true
  }
}
```

Receipts and reports contain safe summaries only. Full private Onshape payloads
may be held in memory for validation but are not copied into ordinary logs.

## Gateway Policy

The complete plan is preflighted before the first request. The live operation
map is fixed in code:

| Semantic operation | MCP tool and endpoint |
| --- | --- |
| `auth_status` | `onshape_auth_status(validate=true)` |
| `list_documents` | `onshape_api_call(getDocuments)` |
| `get_document` | `onshape_api_call(getDocument)` |
| `list_workspaces` | `onshape_api_call(getDocumentWorkspaces)` |
| `read_elements` | `onshape_api_call(getElementsInDocument)` |
| `body_details` | `onshape_api_call(getPartStudioBodyDetails)` |
| `bounding_boxes` | `onshape_api_call(getPartStudioBoundingBoxes)` |
| `mass_properties` | `onshape_api_call(getPartStudioMassProperties)` |

The Gateway rejects unknown endpoint names, non-GET operations, arbitrary URL
or header parameters, bodies, file references, auth-login tool calls, export,
screenshot, and every mutation. `wvm` is restricted to `w`, `v`, or `m`, list
limits are bounded, and identifiers must match the approved scope.

Tool annotations from the upstream MCP are informational only and are not a
security boundary.

## Readback and Completion Semantics

A network request is not sufficient for success. Live completion requires:

1. the full plan passed policy before dispatch;
2. the MCP request completed without protocol or API error;
3. the response matched the approved scope and expected invariant;
4. a typed readback receipt was produced;
5. the final report states `execution_mode=live`, the transport name,
   `network_request_sent=true`, and `readback_verified=true`.

Authentication errors, scope mismatches, malformed responses, timeouts, rate
limits, and missing readback produce stable error codes and never a completed
status. The offline example is permanently bound to `RecordingTransport` and
cannot become live because environment credentials happen to exist.

## CLI and Doctor

New or extended commands:

- `onshape-agent auth status --json`: safe local configuration summary.
- `onshape-agent doctor --live --json`: explicit authenticated session probe.
- `onshape-agent live list-documents --limit 1`: bounded discovery smoke test.
- `onshape-agent live read-document --document-id <id>`: scope-bound readback.

The default `doctor` remains network-free. Status values are
`READY_OFFLINE`, `READY_LIVE`, `AUTH_REQUIRED`, and `NOT_READY`. Reports never
include tokens, secrets, authorization headers, callback query parameters,
user email addresses, or document bodies.

## Error Handling

- MCP process launch and initialization failures map to `TRANSPORT_UNAVAILABLE`.
- Request timeout or process exit maps to `TRANSPORT_FAILED`.
- `401` or expired login maps to `AUTH_REQUIRED`.
- `403` maps to `SCOPE_DENIED`.
- `404` maps to `NOT_FOUND`.
- `429` maps to `RATE_LIMITED` without an automatic mutating retry.
- Invalid JSON or an unexpected content shape maps to `INVALID_RESPONSE`.
- Readback mismatch maps to `VERIFICATION_FAILED`.

Errors are sanitized before entering JSONL events or CLI output. OAuth login is
not initiated implicitly after an error.

## Test Strategy

Implementation follows test-first development. Independent tests define the
route and policy oracle before production code.

1. MCP stdio lifecycle and timeout tests use a deterministic fake child server.
2. Transport tests prove the fixed endpoint map and reject raw inputs.
3. Gateway tests prove whole-plan preflight and no partial dispatch.
4. Readback tests prove scope matching and failure on absent or mismatched
   evidence.
5. Doctor tests prove default offline behavior and explicit live probing.
6. Redaction tests seed recognizable fake secrets into headers, URLs, errors,
   and bodies and assert they never reach reports or logs.
7. Mutation or negative-control tests replace one allowed GET with a delete or
   disable scope checking and must fail.
8. Distribution tests require version `1.11.0` everywhere and verify installer
   output contains no credentials.
9. A real authenticated smoke test is opt-in and excluded from default CI. It
   validates session status and one readback without mutating Onshape.

Release acceptance requires the full unit suite, Ruff, plugin and skill
validation, offline example verification, live doctor, one real document
readback, clean secret scan, clean Git worktree, and remote/tag verification.

## Compatibility and Migration

Existing offline commands and fixtures retain their behavior. New schema
fields have explicit defaults for simulated runs. The live transport is opt-in;
no environment variable can silently switch an offline example to live mode.

The current `CadTransport.dispatch()` dictionary contract is replaced by a
typed receipt inside this release. Because there is no published third-party
transport API yet, no deprecated adapter is retained. This keeps one clear
long-term contract rather than accumulating compatibility code.

## Documentation and Project Memory

README and authentication documentation must distinguish installation,
authorization, live connection, and live mutation. Project logs record each
implemented slice, commands used for verification, upstream MCP version, and
non-obvious issues. `PROJECT_MEMORY.md` records reusable project-specific
pitfalls, especially MCP scope behavior, version pinning, readback requirements,
and Windows stdio handling.
