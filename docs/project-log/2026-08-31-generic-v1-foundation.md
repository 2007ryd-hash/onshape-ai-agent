# 2026-08-31 Generic V1 Foundation

## What changed

- Reframed the repository as a general engineering-to-Onshape automation foundation.
- Added strict artifact, task graph, CAD plan, Drawing plan, visual report, and diagnosis contracts.
- Added task-dependent graph selection and bounded repair routing owned by the main orchestrator.
- Added a deterministic CAD Gateway with a deny-by-default operation policy and injected transport.
- Added immutable artifact storage, SHA-256 metadata, append-only JSONL events, and recursive secret redaction.
- Added a network-free CLI demonstration and independent tests.

## Why

Model workers must not control external CAD systems directly. The first release establishes a testable boundary where models propose artifacts and deterministic code decides whether anything may be dispatched.

## How tested

- Contract rejection tests for unknown fields, invalid graph edges, graph cycles, and incomplete drawings.
- Gateway tests for prohibited and unknown operations, unapproved assumptions, dependency ordering, and zero network dispatch.
- Orchestrator tests for conditional task graphs and repair routing.
- Run-log tests for append behavior, immutable artifacts, hashing, and secret redaction.
- CLI acceptance test for generated artifacts and ordered events.
- Mutation test: temporarily allowing `delete_workspace` caused the safety test to fail, proving that the test detects a dangerous allowlist regression; the mutation was then reverted and the full suite passed again.

## Expected result

The local demo produces a complete audit trail and routes a simulated visual mate issue back to the CAD Agent without contacting Onshape.

## Known limitations

- No live LLM, Onshape, Drawing, vision, or physics-solver adapter is included in V1.
- Visual inputs in the demo are explicitly simulated artifact identifiers.
- The Gateway currently records approved operations rather than translating them to REST requests.

## Backup and publication

Before repository replacement, the previous complete Git history was saved outside the repository as a verified Git bundle. The initial verification command was first run without repository context and failed; rerunning it with the source repository context verified the bundle successfully.

## Next step

Run the safe V1 test, review the artifacts, then implement a read-only Onshape discovery adapter before enabling any cloud writes.

## Publication result

The generic root history replaced the private repository's previous `main` using an exact `--force-with-lease` guard. The repository remained private, and the remote head was verified after publication.
