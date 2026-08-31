# Project Context

This repository is a course-independent foundation for supervised engineering-to-Onshape automation. The main orchestrator owns approvals and repair routing. Model workers produce immutable artifacts; deterministic code controls calculation, policy, execution, and verification.

# Pitfalls

- Never give CAD or Drawing workers direct API credentials or network access.
- Never treat Markdown explanations as authoritative dimensions or approvals.
- Never dispatch any plan until the complete plan passes allowlist, scope, dependency, and assumption checks.
- Never allow visual QA to certify geometry without deterministic read-back evidence.
- Never overwrite artifacts during repair; create a new version and preserve lineage.
- Runtime logs may contain private design data and must remain ignored by Git.
- `git check-ignore .worktrees` does not match a nonexistent directory on this
  Windows checkout; validate `.worktrees/probe` before creating the worktree.
- A fixed full-design pipeline is wrong for reusable skills. Route
  `analysis-only`, `cad-edit`, `drawing-only`, and `full-design` separately.
- Windows subprocess tests must request UTF-8 decoding explicitly because the
  machine locale may otherwise decode PowerShell output as GBK.

# Important Notes

- V1 uses a network-free `RecordingTransport`; it does not modify Onshape.
- Main model profile is `gpt-5.6-sol` with max reasoning.
- Worker profiles use `gpt-5.6-luna` with max reasoning; visual QA additionally requires vision capability.
- `delete_workspace`, raw HTTP, permission, sharing, and unknown actions are denied before dispatch.
- Runtime events are append-only JSONL with recursive secret redaction.
- V1.1 version is `0.2.0`, licensed Apache-2.0, and installs one canonical
  skill into Codex and Claude Code without an LLM provider API key.
- `scripts/install.ps1` writes runtime state under
  `%LOCALAPPDATA%\onshape-engineering-agent`; the installed skill launcher reads
  that state before invoking the project-owned Python runtime.
- `simple-bracket` is a genuine offline artifact workflow, not a live CAD
  model. Its summary must retain `network_request_sent=false` and
  `visual_mode=simulated`.

# Reusable Learnings

- Artifact-only communication prevents speculative prose from silently becoming approved design data.
- Preflight the entire execution plan before dispatching the first action.
- Repair routing belongs to the main orchestrator, not the agent that detected the symptom.
- A recording transport is a useful acceptance boundary before live credentials and adapters exist.
- Test host integration in temporary Codex/Claude directories before touching
  the user's actual configuration.
