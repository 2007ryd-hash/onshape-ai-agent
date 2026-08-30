# Project Context

This repository is a course-independent foundation for supervised engineering-to-Onshape automation. The main orchestrator owns approvals and repair routing. Model workers produce immutable artifacts; deterministic code controls calculation, policy, execution, and verification.

# Pitfalls

- Never give CAD or Drawing workers direct API credentials or network access.
- Never treat Markdown explanations as authoritative dimensions or approvals.
- Never dispatch any plan until the complete plan passes allowlist, scope, dependency, and assumption checks.
- Never allow visual QA to certify geometry without deterministic read-back evidence.
- Never overwrite artifacts during repair; create a new version and preserve lineage.
- Runtime logs may contain private design data and must remain ignored by Git.

# Important Notes

- V1 uses a network-free `RecordingTransport`; it does not modify Onshape.
- Main model profile is `gpt-5.6-sol` with max reasoning.
- Worker profiles use `gpt-5.6-luna` with max reasoning; visual QA additionally requires vision capability.
- `delete_workspace`, raw HTTP, permission, sharing, and unknown actions are denied before dispatch.
- Runtime events are append-only JSONL with recursive secret redaction.

# Reusable Learnings

- Artifact-only communication prevents speculative prose from silently becoming approved design data.
- Preflight the entire execution plan before dispatching the first action.
- Repair routing belongs to the main orchestrator, not the agent that detected the symptom.
- A recording transport is a useful acceptance boundary before live credentials and adapters exist.
