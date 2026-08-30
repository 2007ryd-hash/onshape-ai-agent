# Onshape Engineering Agent

A supervised, artifact-driven foundation for reliable engineering-to-CAD automation.

V1 demonstrates the safety architecture locally:

- a high-reasoning main orchestrator selects a task-dependent graph;
- specialist workers produce strict JSON artifacts rather than chatting directly;
- a deterministic CAD Gateway enforces an operation allowlist before dispatch;
- visual findings are routed through main-agent diagnosis and bounded repair loops;
- every transition and gateway decision is written to an append-only run log.

## Important V1 boundary

V1 does **not** call Onshape, invoke an LLM provider, calculate real structural results, or create live drawings. Its `RecordingTransport` proves that policies, artifacts, routing, and logging work without credentials or network side effects. Live adapters are a later phase after this foundation is tested.

## Architecture

```text
User
  -> Main Orchestrator (Sol-class model)
  -> specialist artifact producer (Luna-class model)
  -> main review gate
  -> typed execution plan
  -> deterministic CAD Gateway
  -> injected transport
  -> deterministic verification
  -> Drawing artifact producer
  -> Visual QA anomaly report
  -> main diagnosis and bounded repair
```

Agents receive only explicitly listed artifacts. JSON is authoritative; Markdown explains decisions but cannot approve dimensions or actions.

## Install

Python 3.12 is required.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Run tomorrow's safe test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m onshape_agent.cli demo --output runs
```

The demo prints JSON similar to:

```json
{
  "network_request_sent": false,
  "repair_target": "cad_agent",
  "status": "REPAIR_ROUTED",
  "visual_mode": "simulated"
}
```

Open the printed run directory and inspect:

```text
manifest.json
events.jsonl
artifacts/task_graph_v1.json
artifacts/execution_plan_v1.json
artifacts/execution_report_v1.json
artifacts/visual_report_v1.json
artifacts/diagnosis_v1.json
```

The visual report is explicitly marked `simulated`; it is a workflow test, not evidence that a CAD model was rendered.

## Gateway safety

V1 allows only typed `ensure_*`, render, export, and read-back operations. Delete, permission, sharing, raw HTTP, credential, and unknown operations are rejected before transport dispatch. Tests verify that a proposed `delete_workspace` operation returns `DENIED` and sends no network request.

## Documentation

- [V1 design](docs/superpowers/specs/2026-08-31-onshape-engineering-agent-v1-design.md)
- [Implementation plan](docs/superpowers/plans/2026-08-31-onshape-engineering-agent-v1.md)
- [Project log](PROJECT_LOG.md)
- [Project memory](PROJECT_MEMORY.md)
