# Onshape Engineering Agent V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a generic, locally testable supervised multi-agent foundation with artifact-only communication, a closed-loop orchestrator, a deny-by-default CAD Gateway, visual/drawing contracts, and auditable logs.

**Architecture:** Strict Pydantic contracts represent all agent artifacts and plans. A deterministic orchestrator selects capabilities and routes repairs, while a deterministic Gateway validates proposed CAD actions and uses an injected transport; V1 uses a recording transport and never calls Onshape.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, pytest, Ruff, JSON/JSONL.

---

## File map

- `src/onshape_agent/contracts.py`: artifact, task graph, execution plan, visual report, and diagnosis schemas.
- `src/onshape_agent/policy.py`: allowed operations and fail-closed plan validation.
- `src/onshape_agent/gateway.py`: deterministic action execution through an injected transport.
- `src/onshape_agent/orchestrator.py`: task selection, gates, diagnosis, and bounded repair state.
- `src/onshape_agent/runlog.py`: append-only run event writer and manifest creation.
- `src/onshape_agent/demo.py`: safe local V1 scenario.
- `src/onshape_agent/cli.py`: CLI commands for demo and plan validation.
- `tests/`: independent contract, policy, orchestrator, logging, and CLI acceptance tests.

### Task 1: Package and strict contracts

- [x] Write failing tests proving extra JSON fields, invalid artifact types, unapproved assumptions, and malformed task edges are rejected.
- [x] Implement strict Pydantic contracts with versioned enums and discriminated action models.
- [x] Run `python -m pytest tests/test_contracts.py -q`; expect all contract tests to pass.
- [x] Commit `feat: add versioned engineering artifacts`.

### Task 2: Deny-by-default CAD Gateway

- [x] Write failing tests for `delete_workspace`, unknown actions, missing approval hashes, and allowlisted recording operations.
- [x] Implement plan policy validation before transport dispatch and return typed `DENIED` decisions with `network_request_sent=false`.
- [x] Run `python -m pytest tests/test_gateway.py -q`; expect all gateway tests to pass.
- [x] Commit `feat: add deterministic CAD gateway policy`.

### Task 3: Task graph and closed-loop orchestrator

- [x] Write failing tests for full-design, CAD-edit, drawing-only, and analysis-only graph selection.
- [x] Write failing tests routing mate issues to CAD, drawing issues to Drawing, and exhausted repairs to `BLOCKED`.
- [x] Implement capability selection, main review gates, diagnosis routing, and bounded repair counters.
- [x] Run `python -m pytest tests/test_orchestrator.py -q`; expect all orchestrator tests to pass.
- [x] Commit `feat: orchestrate bounded engineering repair loops`.

### Task 4: Immutable artifacts and project logging

- [x] Write failing tests proving events append rather than overwrite and secrets are redacted.
- [x] Implement run manifests, SHA-256 artifact metadata, atomic artifact writes, and append-only JSONL events.
- [x] Add `PROJECT_LOG.md`, `PROJECT_MEMORY.md`, and the first sanitized development entry.
- [x] Run `python -m pytest tests/test_runlog.py -q`; expect all logging tests to pass.
- [x] Commit `feat: add auditable run artifacts and logs`.

### Task 5: Safe CLI demonstration

- [x] Write a failing CLI test for `onshape-agent demo --output <temp>`.
- [x] Implement a generic base-plate plan containing sketch and extrude actions, execute it through the recording Gateway, emit a visual finding, diagnose it, and write the run log.
- [x] Run `python -m pytest tests/test_cli.py -q`; expect the CLI test to pass without network or credentials.
- [x] Commit `feat: add safe supervised pipeline demo`.

### Task 6: Documentation and publication verification

- [x] Document installation, architecture, test commands, demo output, V1 limitations, and tomorrow's manual test.
- [x] Run `python -m pytest -q` and `python -m ruff check .`; expect clean results.
- [x] Scan tracked files for credentials, course names, Week fixtures, and absolute course paths; expect no matches other than explicit generic documentation statements.
- [x] Commit `docs: publish generic V1 workflow`.
- [x] Push the new root commit to remote `main` with an exact `--force-with-lease` value, then verify remote HEAD and repository visibility.

## Self-review

The plan covers artifact-only communication, deterministic execution, CAD and Drawing isolation, visual specification comparison, bounded repair loops, task-dependent graphs, project logs, model-role configuration, safe repository replacement, and a network-free V1 test. It intentionally postpones real Onshape transport, LLM provider calls, physics solvers, and live Drawing creation until the safety foundation is tested.
