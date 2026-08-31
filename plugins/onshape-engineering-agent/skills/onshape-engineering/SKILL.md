---
name: onshape-engineering
description: "Use for supervised engineering-to-CAD work covering CAD parts, assemblies, mates, engineering drawings, structured engineering analysis, geometry verification, and repair planning. Keep the workflow artifact-only, use the local onshape-agent CLI, and make approval and simulated or live execution status explicit."
---

# Onshape Engineering

Use this skill when a request needs an auditable engineering workflow rather
than an unstructured CAD conversation. It covers CAD parts, assemblies, mates,
engineering drawings, structured engineering analysis, geometry verification,
and bounded repair planning.

The host agent owns the workflow and approvals. Specialist workers are bounded
artifact producers. They do not chat with one another, approve a design, or
call Onshape directly.

## Artifact-only boundary

- JSON is authoritative state. Markdown may explain a decision, but it
  cannot approve dimensions, actions, or a repair.
- Read [the artifact contract reference](references/artifact-contracts.md)
  before creating or validating a specialist artifact.
- Keep every artifact immutable. A repair creates a new version and preserves
  the input and content hashes of the previous version.
- Label every value that is not established by the request with exactly one of
  `UNKNOWN`, `NEEDS_CONFIRMATION`, or `ASSUMPTION`. Use `KNOWN` only when the
  source is explicit and unambiguous.
- Never dispatch an action with an unresolved `UNKNOWN` value. Pause for the
  user when a critical value is `NEEDS_CONFIRMATION`; an `ASSUMPTION` requires
  explicit main-host approval before it can affect an execution plan.

Workers may produce only the JSON files named by their contracts. Do not give a
worker Onshape credentials, an API client, an MCP connection, a browser session,
or arbitrary network access. In particular, a worker must never call Onshape
directly. The main host reviews worker artifacts, and the deterministic local
runtime is the only execution boundary.

## Required workflow

Follow this sequence for every request, even when a stage is short:

```text
intake -> requirement artifact -> main review -> CAD execution plan -> local `onshape-agent` command -> drawing plan -> verification -> final review
```

1. **Intake** - classify the request as analysis, CAD, assembly, drawing, or
   verification work. Capture units, scope, source references, and requested
   deliverables without inventing dimensions.
2. **Requirement artifact** - write the host-owned requirement JSON and label
   every value. Record missing information as `UNKNOWN` or
   `NEEDS_CONFIRMATION`, and record any proposed interpretation as an
   `ASSUMPTION`.
3. **Main review** - have the main host check scope, dependencies, hashes,
   assumptions, and policy before dispatching a worker. The main host is the
   sole approval gate.
4. **CAD execution plan** - route to the smallest applicable specialist and
   collect its exact JSON outputs. Build an execution plan only from approved,
   typed artifacts and keep the target inside the selected document scope.
5. **Local CLI command** - invoke the installed local `onshape-agent` CLI for
   deterministic validation, planning, execution through the configured
   transport, and read-back. Start with `onshape-agent --help`; use a concrete
   command such as `onshape-agent demo --output <run-directory>` only when it
   matches the requested workflow. Do not substitute a provider SDK or a
   direct HTTP request.
6. **Drawing plan** - when a drawing is requested or required for review,
   route the approved design and execution evidence to the drawing specialist.
   State projection, units, scale, and required views in its JSON artifact.
7. **Verification** - compare deterministic read-back evidence with the
   approved specification. Visual QA may report an observation, but it cannot
   certify geometry or override JSON evidence.
8. **Final review** - the main host reconciles all artifacts, records any
   unresolved issue, and either completes the run, asks the user for
   confirmation, or routes one bounded repair. A worker never chooses its own
   repair target.

## Routing and repair

Use the specialist contracts under the plugin's `agents/` directory:

| Request or finding | Specialist artifact producer |
| --- | --- |
| engineering model or structured analysis | `engineering-agent` |
| part, assembly, mate, or geometry execution plan | `cad-agent` |
| engineering drawing layout and projection | `drawing-agent` |
| render comparison or visual uncertainty | `visual-qa-agent` |

The main host may combine these stages, but it must preserve the artifact
lineage and review each hand-off. Diagnosis and repair routing belong to the
main host agent. If a worker reports an error, route it through the host's
typed diagnosis; do not let the worker approve, retry, or rewrite another
worker's artifact.

## Execution disclosure

Every user-facing summary and final run manifest must disclose both the mode and
the side-effect boundary. Include:

- `execution_mode`: `simulated` or `live`;
- `network_request_sent`: `false` or `true`;
- the selected transport and the run/artifact identifiers;
- whether geometry was deterministically read back, visually observed, or only
  simulated.

For this installable V1.1 workflow, the included example is `simulated`, uses
the recording transport, and sends no network request. Never describe a
simulated result as a live Onshape modification. A `live` label is permitted
only when a configured, authorized transport reports a real request and the
read-back evidence is present; otherwise state `simulated` or
`not_configured` and stop at the safe boundary.
