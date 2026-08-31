# Artifact Contracts

This reference defines the hand-off boundary for the `onshape-engineering`
skill. The JSON artifact is authoritative source of truth. Only the main host may explain
validated JSON to the user; that Markdown explanation cannot add dimensions,
approve an action, or change a repair route. Workers do not emit Markdown.

## Common envelope

Every persisted artifact is an immutable JSON document with a metadata envelope
and a typed payload. The metadata must include:

```json
{
  "artifact_id": "unique-stable-id",
  "artifact_type": "contract-defined-type",
  "run_id": "run-id",
  "producer": "main-host-or-specialist",
  "created_at": "UTC timestamp",
  "input_hashes": ["sha256:..."],
  "content_hash": "sha256:...",
  "approval_status": "PENDING"
}
```

These fields mirror the current `RunLog` metadata. Metadata never carries
`schema_version`; a typed payload contract may include `schema_version` when
that contract defines one.

`approval_status` is controlled by the main host. A worker can propose a
`PENDING` artifact, but it cannot mark its own output `APPROVED` or
`REJECTED`. A repair must create a new artifact ID and retain the previous
artifact's hash in `input_hashes`; overwriting an artifact loses auditability.

## Value status

Every requirement or design value carries a unit and exactly one source-status
label:

| Status | Meaning | Dispatch rule |
| --- | --- | --- |
| `KNOWN` | Explicitly supplied or deterministically read back. | May be used when the scope and units are clear. |
| `ASSUMPTION` | A proposed interpretation that is not in the source request. | Must be recorded and approved by the main host before use. |
| `UNKNOWN` | Required information is absent or cannot be determined. | Blocks dependent planning and execution. |
| `NEEDS_CONFIRMATION` | A choice is available but the user must decide. | Pause at the user-confirmation gate. |

Do not hide an unknown value in prose, a default, or a worker prompt. If a
value changes geometry, a mate, a drawing dimension, or an execution action,
the status must be visible in JSON before the main host reviews it.

## Specialist output contracts

Specialists are artifact-only workers. Each may create only the JSON files in
its row and no other deliverable files:

| Producer | Allowed inputs | Exact JSON outputs |
| --- | --- | --- |
| `engineering-agent` | Approved requirement artifact and explicitly supplied engineering context. | `engineering_model.json`, `analysis_result.json` |
| `cad-agent` | Approved requirement, engineering, analysis, and design artifacts named by the main host. | `cad_spec.json`, `execution_plan.json` |
| `drawing-agent` | Approved design/CAD evidence and drawing requirements named by the main host. | `drawing_plan.json` |
| `visual-qa-agent` | Approved CAD/drawing renders and the reference specification. | `visual_report.json` |

Each output must identify its producer, input artifact hashes, assumptions, and
approval status. A worker must not create another worker's output, edit an
existing version, emit an approval artifact, or emit Markdown. If a user-facing
explanation is needed, the main host derives it from the validated JSON; it is
not a substitute for one of these JSON files.

### `engineering_model.json`

Contains the structured model, units, coordinate or boundary conditions, and
the status of every value needed for analysis. It records assumptions and
unknowns explicitly; it does not claim a calculation that has not run.

### `analysis_result.json`

Contains deterministic or clearly identified analysis inputs, method, outputs,
units, checks, and limitations. The worker may propose an analysis; it cannot
grant engineering sign-off or silently turn an assumption into a known value.

### `cad_spec.json`

Contains the approved design interpretation, semantic feature identifiers,
dimensions, dependencies, target document scope, and value statuses needed to
construct or verify a part, assembly, or mate.

### `execution_plan.json`

Contains only typed, allowlisted actions with dependencies, target scope, and
the approved design hash. The main host must validate and approve it before the
local runtime or CAD Gateway receives it.

### `drawing_plan.json`

Contains drawing units, projection, scale, view identifiers, references to the
approved design, and required dimensions or annotations. It describes a plan;
it is not evidence that a drawing was created in Onshape.

### `visual_report.json`

Contains the comparison mode, render references, observed findings, confidence,
severity, and related semantic IDs. `simulated` observations are workflow
fixtures only; visual QA never overrides deterministic read-back evidence.

## Host-owned gates and disclosure

The main host agent owns requirement review, approval, execution dispatch,
diagnosis, repair routing, and final completion. The deterministic local
`onshape-agent` CLI and its configured Gateway are the only execution boundary.
Workers do not call the Onshape API, SDK, MCP, browser, or raw HTTP endpoint and
must not receive Onshape credentials or direct network access.

Every run records `execution_mode` as `simulated` or `live`, whether
`network_request_sent` is `false` or `true`, the selected transport, and the
read-back evidence. V1.1's recording transport is `simulated` and sends no
network request. A live label is valid only when an authorized live transport
confirms a real request and deterministic read-back; a simulation must never be
reported as a live Onshape modification.
