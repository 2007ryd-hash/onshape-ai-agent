# Onshape Engineering Agent V1 Design

## Product boundary

V1 is a course-independent foundation for supervised engineering-to-CAD automation. It does not claim production certification, general finite-element analysis, or autonomous control of Onshape. It proves that model workers can propose typed artifacts while deterministic code controls validation, state transitions, logging, and every external side effect.

## Principles

1. Agents produce immutable artifacts; they do not chat with one another.
2. LLMs propose models and actions; deterministic components calculate, authorize, execute, and verify.
3. The main orchestrator owns task graphs, approvals, diagnosis, repair routing, and completion.
4. Unapproved assumptions and unknown critical values fail closed.
5. Visual QA discovers anomalies but never overrides geometric or API evidence.
6. Every transition and gateway decision is recorded in an append-only run log.

## Roles

- **Main Orchestrator**: high-reasoning model such as `gpt-5.6-sol` with max reasoning. It selects a task-dependent graph, reviews artifacts, approves plans, diagnoses failures, and routes bounded repairs.
- **Engineering Agent**: worker model such as `gpt-5.6-luna` with max reasoning. It proposes an engineering model; a deterministic solver performs calculations.
- **CAD Agent**: worker model. It produces a typed execution plan but has no Onshape credentials or network capability.
- **Drawing Agent**: worker model. It produces a drawing plan for front, top, right, and optional isometric views; it has no Onshape credentials.
- **Visual QA Agent**: vision-capable worker model. It compares CAD renders and drawing renders with the approved specification and reports possible anomalies.
- **CAD Gateway**: deterministic Python. It enforces the operation allowlist, approval hashes, sandbox scope, dependencies, idempotency, retry limits, and read-back checks before translating approved actions to API requests.

## Artifact contracts

All authoritative state is JSON validated with strict Pydantic models. Markdown is explanatory only. Each artifact has an ID, type, schema version, run ID, producer, timestamp, input hashes, content hash, and approval status. Artifacts are immutable; repairs create new versions.

V1 defines task graphs, execution plans, gateway decisions, visual reports, diagnoses, and run events. Agents receive only explicit artifact references selected by the orchestrator.

## Closed-loop workflow

The orchestrator supports intake, analysis, review, CAD planning, CAD gate, execution, geometry verification, drawing planning, drawing execution, visual QA, diagnosis, repair, user confirmation, final review, complete, and blocked states. Failures are classified as engineering, CAD geometry, assembly mate, drawing, gateway, visual uncertainty, or unresolved requirement. Repairs are bounded by an attempt budget.

## Gateway policy

V1 permits only domain actions such as `ensure_document`, `ensure_part_studio`, `ensure_sketch`, `ensure_extrude`, `ensure_hole`, `ensure_assembly`, `ensure_instance`, `ensure_mate`, `ensure_drawing`, `render_view`, `export_artifact`, and `read_back`. Delete, permission, sharing, raw HTTP, credential, and arbitrary FeatureScript actions are denied before any network call.

V1 ships a recording transport rather than live Onshape writes. This lets the user test policy, planning, logging, repair routing, and task graph behavior safely before credentials and live adapters are added.

## Logging

Each run writes `manifest.json`, `task_graph.json`, immutable artifacts, and append-only `events.jsonl`. Runtime directories are ignored by Git because they may contain user data. Sanitized engineering progress is committed under `docs/project-log/`, while `PROJECT_MEMORY.md` records durable technical learnings.

## V1 acceptance criteria

- A CAD edit task selects CAD, deterministic geometry verification, and visual QA without requiring engineering or drawing agents.
- A full design task selects engineering, CAD, drawing, and visual QA capabilities.
- An unapproved assumption blocks the CAD gate.
- `delete_workspace` and unknown operations are denied with `network_request_sent=false`.
- Approved allowlisted actions reach only the recording transport in V1.
- A visual mate issue is diagnosed and routed to the CAD Agent.
- Repair attempts exceeding the budget enter `BLOCKED`.
- Every state transition and gateway decision appears in the append-only log.
- Tests and static checks run without credentials or network access.
- The active repository contains no course-specific code, fixtures, or absolute course paths.
